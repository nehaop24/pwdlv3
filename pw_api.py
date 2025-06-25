import requests
import json
import re
import base64
import xmltodict
import isodate
import uuid
import logging
from typing import Dict, Optional, Tuple, List
from urllib.parse import urlparse, parse_qs, unquote
from config import config

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class PWAPIError(Exception):
    pass

class LicenseKeyFetcher:
    def __init__(self, token: str, random_id: Optional[str] = None):
        self.token = token
        # Auto-generate random_id if not provided, similar to your Endpoints class
        self.random_id = random_id or str(uuid.uuid4())
        self.url = None
        self.cookies = None
        logger.info(f"Initialized LicenseKeyFetcher with random_id: {self.random_id}")

    def build_license_url(self, encoded_otp_key: str) -> str:
        return f"https://api.penpencil.co/v1/videos/get-otp?key={encoded_otp_key}&isEncoded=true"

    def get_otp_headers(self) -> Dict[str, str]:
        headers = config.DEFAULT_HEADERS.copy()
        headers.update({
            "authorization": f"Bearer {self.token}",
            "randomid": self.random_id,
            "origin": "https://www.pw.live",
            "referer": "https://www.pw.live/",
        })
        logger.debug(f"Generated headers: {json.dumps(headers, indent=2)}")
        return headers

    def key_char_at(self, key: str, i: int) -> int:
        return ord(key[i % len(key)])

    def b64_encode(self, data: bytes) -> str:
        if not data:
            return ""
        return base64.b64encode(bytes(data)).decode('utf-8')

    def get_key_final(self, otp: str) -> str:
        decoded_bytes = base64.b64decode(otp)
        length = len(decoded_bytes)
        decoded_ints = [int(byte) for byte in decoded_bytes]

        result = "".join(
            chr(decoded_ints[i] ^ ord(self.token[i % len(self.token)]))
            for i in range(length)
        )
        return result

    def xor_encrypt(self, data: str) -> List[int]:
        return [ord(c) ^ self.key_char_at(self.token, i) for i, c in enumerate(data)]

    def insert_zeros(self, hex_string: str) -> str:
        result = "00"
        for i in range(0, len(hex_string), 2):
            result += hex_string[i:i+2]
            if i + 2 < len(hex_string):
                result += "00"
        return result

    def extract_kid_from_mpd(self, url: str) -> Optional[str]:
        try:
            logger.info(f"Fetching MPD from: {url}")
            response = requests.get(url)
            logger.debug(f"MPD response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch MPD. Status: {response.status_code}, Response: {response.text}")
                raise PWAPIError(f"Failed to fetch MPD content. Status code: {response.status_code}")
            
            mpd_content = response.text
            logger.debug(f"MPD content length: {len(mpd_content)}")
            
            pattern = r'default_KID="([0-9a-fA-F-]+)"'
            match = re.search(pattern, mpd_content)
            kid = match.group(1) if match else None
            logger.info(f"Extracted KID: {kid}")
            return kid
        except Exception as e:
            logger.error(f"Error extracting KID: {str(e)}")
            raise PWAPIError(f"Error extracting KID: {str(e)}")

    def parse_direct_link(self, link: str) -> Tuple[str, str, str]:
        """Parse direct MPD link to extract video_id, batch_id, and MPD URL"""
        try:
            logger.info(f"Parsing direct link: {link}")
            
            # Split by the colon to separate name and URL
            if ':' in link:
                name, url = link.split(':', 1)
                name = name.strip()
            else:
                url = link.strip()
                name = "Video"
            
            # Parse URL to extract parentId and childId
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            
            parent_id = query_params.get('parentId', [None])[0]
            child_id = query_params.get('childId', [None])[0]
            
            logger.info(f"Parsed - Name: {name}, Parent ID: {parent_id}, Child ID: {child_id}")
            
            if not parent_id or not child_id:
                raise PWAPIError("Could not extract parentId or childId from URL")
            
            return child_id, parent_id, name
            
        except Exception as e:
            logger.error(f"Error parsing direct link: {str(e)}")
            raise PWAPIError(f"Error parsing direct link: {str(e)}")

    def test_token_validity(self) -> bool:
        """Test if the token is valid by making a simple API call"""
        try:
            headers = self.get_otp_headers()
            # Use a simple endpoint to test token validity
            test_url = "https://api.penpencil.co/v1/users/me"
            logger.info(f"Testing token validity with URL: {test_url}")
            
            response = requests.get(test_url, headers=headers)
            logger.info(f"Token test response status: {response.status_code}")
            logger.debug(f"Token test response: {response.text}")
            
            if response.status_code == 200:
                logger.info("Token is valid")
                return True
            else:
                logger.warning(f"Token test failed with status {response.status_code}")
                # Try alternative endpoint
                alt_test_url = "https://api.penpencil.co/v1/videos/video-url-details?type=BATCHES&childId=680c85b0c9d776d19b869d3f&parentId=65d75d320531c20018ade9bb&reqType=query&videoContainerType=DASH"
                logger.info(f"Trying alternative test URL: {alt_test_url}")
                
                alt_response = requests.get(alt_test_url, headers=headers)
                logger.info(f"Alternative test response status: {alt_response.status_code}")
                logger.debug(f"Alternative test response: {alt_response.text}")
                
                return alt_response.status_code == 200
                
        except Exception as e:
            logger.error(f"Error testing token validity: {str(e)}")
            return False

    def get_video_url_and_key(self, video_id: str, batch_id: str) -> Tuple[str, str, str]:
        """Get video URL and decryption key"""
        try:
            logger.info(f"Getting video URL and key for video_id: {video_id}, batch_id: {batch_id}")
            
            # Get video URL details
            url_endpoint = f"https://api.penpencil.co/v1/videos/video-url-details?type=BATCHES&childId={video_id}&parentId={batch_id}&reqType=query&videoContainerType=DASH"
            logger.info(f"Video URL endpoint: {url_endpoint}")
            
            headers = self.get_otp_headers()
            response = requests.get(url_endpoint, headers=headers)
            
            logger.info(f"Video URL response status: {response.status_code}")
            logger.debug(f"Video URL response: {response.text}")
            
            if response.status_code != 200:
                raise PWAPIError(f"Failed to get video URL. Status: {response.status_code}, Response: {response.text}")
            
            data = response.json()
            logger.debug(f"Video URL data: {json.dumps(data, indent=2)}")
            
            if not data.get('success') or 'data' not in data:
                raise PWAPIError(f"Invalid response from video URL API: {data}")
            
            video_data = data['data']
            base_url = video_data['url']
            signature = video_data['signedUrl']
            
            logger.info(f"Base URL: {base_url}")
            logger.debug(f"Signature: {signature}")
            
            # Build full URL
            full_url = f"{base_url}{signature}"
            self.url = full_url
            logger.info(f"Full MPD URL: {full_url}")
            
            # Extract cookies from signature
            self.cookies = self._extract_cookies_from_signature(signature)
            logger.debug(f"Extracted cookies: {self.cookies}")
            
            # Extract KID from MPD
            kid = self.extract_kid_from_mpd(full_url)
            if not kid:
                raise PWAPIError("Could not extract KID from MPD")
            
            kid_clean = kid.replace("-", "")
            logger.info(f"Clean KID: {kid_clean}")
            
            # Get decryption key
            otp_key = self.b64_encode(self.xor_encrypt(kid_clean))
            logger.debug(f"OTP key: {otp_key}")
            
            encoded_otp_key_step1 = otp_key.encode('utf-8').hex()
            encoded_otp_key = self.insert_zeros(encoded_otp_key_step1)
            logger.debug(f"Encoded OTP key: {encoded_otp_key}")
            
            license_url = self.build_license_url(encoded_otp_key)
            logger.info(f"License URL: {license_url}")
            
            response = requests.get(license_url, headers=headers)
            logger.info(f"License response status: {response.status_code}")
            logger.debug(f"License response: {response.text}")
            
            if response.status_code != 200:
                raise PWAPIError(f"Failed to get license. Status: {response.status_code}, Response: {response.text}")
            
            license_data = response.json()
            logger.debug(f"License data: {json.dumps(license_data, indent=2)}")
            
            if not license_data.get('success') or 'data' not in license_data:
                raise PWAPIError(f"Invalid response from license API: {license_data}")
            
            key = self.get_key_final(license_data['data']['otp'])
            logger.info(f"Decryption key: {key}")
            
            return full_url, key, self.cookies
            
        except Exception as e:
            logger.error(f"Error getting video URL and key: {str(e)}")
            raise PWAPIError(f"Error getting video URL and key: {str(e)}")

    def get_video_url_and_key_from_direct_link(self, mpd_url: str) -> Tuple[str, str, str]:
        """Get decryption key for direct MPD URL"""
        try:
            logger.info(f"Getting key for direct MPD URL: {mpd_url}")
            
            # Extract KID from MPD
            kid = self.extract_kid_from_mpd(mpd_url)
            if not kid:
                raise PWAPIError("Could not extract KID from MPD")
            
            kid_clean = kid.replace("-", "")
            logger.info(f"Clean KID: {kid_clean}")
            
            # Get decryption key
            otp_key = self.b64_encode(self.xor_encrypt(kid_clean))
            logger.debug(f"OTP key: {otp_key}")
            
            encoded_otp_key_step1 = otp_key.encode('utf-8').hex()
            encoded_otp_key = self.insert_zeros(encoded_otp_key_step1)
            logger.debug(f"Encoded OTP key: {encoded_otp_key}")
            
            license_url = self.build_license_url(encoded_otp_key)
            logger.info(f"License URL: {license_url}")
            
            headers = self.get_otp_headers()
            
            response = requests.get(license_url, headers=headers)
            logger.info(f"License response status: {response.status_code}")
            logger.debug(f"License response: {response.text}")
            
            if response.status_code != 200:
                raise PWAPIError(f"Failed to get license. Status: {response.status_code}, Response: {response.text}")
            
            license_data = response.json()
            logger.debug(f"License data: {json.dumps(license_data, indent=2)}")
            
            if not license_data.get('success') or 'data' not in license_data:
                raise PWAPIError(f"Invalid response from license API: {license_data}")
            
            key = self.get_key_final(license_data['data']['otp'])
            logger.info(f"Decryption key: {key}")
            
            # Extract cookies from URL if present
            self.cookies = self._extract_cookies_from_url(mpd_url)
            logger.debug(f"Extracted cookies: {self.cookies}")
            
            return mpd_url, key, self.cookies
            
        except Exception as e:
            logger.error(f"Error getting key for direct link: {str(e)}")
            raise PWAPIError(f"Error getting key for direct link: {str(e)}")

    def _extract_cookies_from_signature(self, signature: str) -> str:
        """Extract cookies from URL signature"""
        try:
            # Parse query parameters from signature
            params = {}
            if "?" in signature:
                query_string = signature.split('?')[1]
            else:
                query_string = signature
            
            for param in query_string.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = value
            
            # Map to CloudFront cookie format
            cookie_mappings = {
                'Policy': 'CloudFront-Policy',
                'Signature': 'CloudFront-Signature', 
                'Key-Pair-Id': 'CloudFront-Key-Pair-Id'
            }
            
            cookies = []
            for param_key, cookie_key in cookie_mappings.items():
                if param_key in params:
                    cookies.append(f"{cookie_key}={params[param_key]}")
            
            return '; '.join(cookies)
        except Exception:
            return ""

    def _extract_cookies_from_url(self, url: str) -> str:
        """Extract cookies from full MPD URL"""
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            
            cookie_mappings = {
                'Policy': 'CloudFront-Policy',
                'Signature': 'CloudFront-Signature', 
                'Key-Pair-Id': 'CloudFront-Key-Pair-Id'
            }
            
            cookies = []
            for param_key, cookie_key in cookie_mappings.items():
                if param_key in query_params:
                    cookies.append(f"{cookie_key}={query_params[param_key][0]}")
            
            return '; '.join(cookies)
        except Exception:
            return ""

class MPDParser:
    def __init__(self, url: str):
        self.url = url
        self.base_url = ""
        self.signature = ""
        self.mpd_dict = None
        
        if "?" in url:
            self.base_url, self.signature = url.split("?", 1)
            if self.base_url.endswith("/master.mpd"):
                self.base_url = self.base_url.split("master.mpd")[0]
        
        logger.info(f"Initialized MPDParser with base_url: {self.base_url}")

    def load_and_parse(self) -> Dict:
        """Load and parse MPD manifest"""
        try:
            logger.info(f"Loading MPD from: {self.url}")
            response = requests.get(self.url)
            logger.info(f"MPD load response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Failed to load MPD. Response: {response.text}")
                raise PWAPIError(f"Failed to load MPD manifest. Status: {response.status_code}")
            
            logger.debug(f"MPD content length: {len(response.text)}")
            self.mpd_dict = xmltodict.parse(response.text, process_namespaces=False)
            logger.info("MPD parsed successfully")
            return self.mpd_dict
        except Exception as e:
            logger.error(f"Error parsing MPD: {str(e)}")
            raise PWAPIError(f"Error parsing MPD: {str(e)}")

    def build_url(self, media: str, segment: Optional[int] = None) -> str:
        """Build full URL for media segment"""
        if media.startswith("http"):
            return media
        
        processed_base_url = self.base_url
        if not processed_base_url.endswith('/'):
            processed_base_url += '/'
        
        processed_media = media
        if processed_media.startswith('/'):
            processed_media = processed_media[1:]

        url = f"{processed_base_url}{processed_media}"
        if segment is not None:
            url = url.replace("$Number$", str(segment))
        
        return f"{url}?{self.signature}" if self.signature else url

    def get_available_qualities(self) -> List[Dict]:
        """Get available video qualities"""
        if not self.mpd_dict:
            self.load_and_parse()
        
        try:
            logger.info("Extracting available qualities")
            period = self.mpd_dict["MPD"]["Period"]
            if isinstance(period, list):
                period = period[0]
            
            adaptation_sets = period["AdaptationSet"]
            if not isinstance(adaptation_sets, list):
                adaptation_sets = [adaptation_sets]
            
            qualities = []
            
            for adaptation_set in adaptation_sets:
                content_type = adaptation_set.get("@contentType", "")
                
                if content_type == "video":
                    representations = adaptation_set.get("Representation", [])
                    if not isinstance(representations, list):
                        representations = [representations]
                    
                    for rep in representations:
                        height = rep.get("@height")
                        width = rep.get("@width")
                        bandwidth = rep.get("@bandwidth")
                        
                        if height:
                            quality_label = f"{height}p"
                            if width:
                                quality_label = f"{width}x{height}"
                            
                            qualities.append({
                                "height": int(height),
                                "width": int(width) if width else None,
                                "bandwidth": int(bandwidth) if bandwidth else None,
                                "label": quality_label
                            })
            
            # Sort by height (quality) descending
            qualities.sort(key=lambda x: x["height"], reverse=True)
            logger.info(f"Found {len(qualities)} video qualities: {[q['label'] for q in qualities]}")
            return qualities
            
        except Exception as e:
            logger.error(f"Error extracting qualities: {str(e)}")
            raise PWAPIError(f"Error extracting qualities: {str(e)}")

    def get_segment_urls(self, target_height: Optional[int] = None) -> Dict:
        """Extract all segment URLs for audio and video with quality selection"""
        if not self.mpd_dict:
            self.load_and_parse()
        
        try:
            logger.info(f"Extracting segment URLs with target height: {target_height}")
            period = self.mpd_dict["MPD"]["Period"]
            if isinstance(period, list):
                period = period[0]
            
            adaptation_sets = period["AdaptationSet"]
            if not isinstance(adaptation_sets, list):
                adaptation_sets = [adaptation_sets]
            
            result = {
                'video': {'init': None, 'segments': {}},
                'audio': {'init': None, 'segments': {}}
            }
            
            for adaptation_set in adaptation_sets:
                content_type = adaptation_set.get("@contentType", "")
                logger.debug(f"Processing adaptation set: {content_type}")
                
                if content_type in ["video", "audio"]:
                    representations = adaptation_set.get("Representation", [])
                    if not isinstance(representations, list):
                        representations = [representations]
                    
                    # Select representation based on quality preference
                    if content_type == "video" and len(representations) > 1:
                        if target_height:
                            # Find exact match or closest
                            best_rep = min(representations, 
                                         key=lambda x: abs(int(x.get("@height", "0")) - target_height))
                            logger.info(f"Selected video quality: {best_rep.get('@height')}p (target: {target_height}p)")
                        else:
                            # Default to highest quality
                            best_rep = max(representations, 
                                         key=lambda x: int(x.get("@height", "0")))
                            logger.info(f"Selected highest video quality: {best_rep.get('@height')}p")
                        representation = best_rep
                    else:
                        representation = representations[0]
                        if content_type == "audio":
                            logger.info("Selected audio representation")
                    
                    segment_template = representation.get("SegmentTemplate", {})
                    
                    # Get init URL
                    init_template = segment_template.get("@initialization", "")
                    if init_template:
                        result[content_type]['init'] = self.build_url(init_template)
                        logger.debug(f"{content_type} init URL: {result[content_type]['init']}")
                    
                    # Get segment URLs
                    media_template = segment_template.get("@media", "")
                    start_number = int(segment_template.get("@startNumber", "1"))
                    
                    # Calculate number of segments from timeline
                    timeline = segment_template.get("SegmentTimeline", {}).get("S", [])
                    if not isinstance(timeline, list):
                        timeline = [timeline]
                    
                    segment_count = 0
                    for s_element in timeline:
                        segment_count += 1
                        if "@r" in s_element:
                            segment_count += int(s_element["@r"])
                    
                    logger.info(f"{content_type} segments: {segment_count} (starting from {start_number})")
                    
                    # Generate segment URLs
                    for i in range(start_number, segment_count + 1):
                        result[content_type]['segments'][i] = self.build_url(media_template, i)
            
            logger.info(f"Generated URLs - Audio: {len(result['audio']['segments'])}, Video: {len(result['video']['segments'])}")
            return result
            
        except Exception as e:
            logger.error(f"Error extracting segment URLs: {str(e)}")
            raise PWAPIError(f"Error extracting segment URLs: {str(e)}")