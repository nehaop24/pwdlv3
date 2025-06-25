import requests
import json
import re
import base64
import xmltodict
import isodate
import uuid
from typing import Dict, Optional, Tuple, List
from urllib.parse import urlparse, parse_qs, unquote
from config import config

class PWAPIError(Exception):
    pass

class LicenseKeyFetcher:
    def __init__(self, token: str, random_id: Optional[str] = None):
        self.token = token
        # Auto-generate random_id if not provided, similar to your Endpoints class
        self.random_id = random_id or str(uuid.uuid4())
        self.url = None
        self.cookies = None

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
            response = requests.get(url)
            if response.status_code != 200:
                raise PWAPIError(f"Failed to fetch MPD content. Status code: {response.status_code}")
            
            mpd_content = response.text
            pattern = r'default_KID="([0-9a-fA-F-]+)"'
            match = re.search(pattern, mpd_content)
            return match.group(1) if match else None
        except Exception as e:
            raise PWAPIError(f"Error extracting KID: {str(e)}")

    def parse_direct_link(self, link: str) -> Tuple[str, str, str]:
        """Parse direct MPD link to extract video_id, batch_id, and MPD URL"""
        try:
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
            
            if not parent_id or not child_id:
                raise PWAPIError("Could not extract parentId or childId from URL")
            
            return child_id, parent_id, name
            
        except Exception as e:
            raise PWAPIError(f"Error parsing direct link: {str(e)}")

    def test_token_validity(self) -> bool:
        """Test if the token is valid by making a simple API call"""
        try:
            headers = self.get_otp_headers()
            # Use a simple endpoint to test token validity
            test_url = "https://api.penpencil.co/v1/users/me"
            response = requests.get(test_url, headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    def get_video_url_and_key(self, video_id: str, batch_id: str) -> Tuple[str, str, str]:
        """Get video URL and decryption key"""
        try:
            # Get video URL details
            url_endpoint = f"https://api.penpencil.co/v1/videos/video-url-details?type=BATCHES&childId={video_id}&parentId={batch_id}&reqType=query&videoContainerType=DASH"
            
            headers = self.get_otp_headers()
            response = requests.get(url_endpoint, headers=headers)
            
            if response.status_code != 200:
                raise PWAPIError(f"Failed to get video URL. Status: {response.status_code}")
            
            data = response.json()
            if not data.get('success') or 'data' not in data:
                raise PWAPIError("Invalid response from video URL API")
            
            video_data = data['data']
            base_url = video_data['url']
            signature = video_data['signedUrl']
            
            # Build full URL
            full_url = f"{base_url}{signature}"
            self.url = full_url
            
            # Extract cookies from signature
            self.cookies = self._extract_cookies_from_signature(signature)
            
            # Extract KID from MPD
            kid = self.extract_kid_from_mpd(full_url)
            if not kid:
                raise PWAPIError("Could not extract KID from MPD")
            
            kid_clean = kid.replace("-", "")
            
            # Get decryption key
            otp_key = self.b64_encode(self.xor_encrypt(kid_clean))
            encoded_otp_key_step1 = otp_key.encode('utf-8').hex()
            encoded_otp_key = self.insert_zeros(encoded_otp_key_step1)
            
            license_url = self.build_license_url(encoded_otp_key)
            
            response = requests.get(license_url, headers=headers)
            if response.status_code != 200:
                raise PWAPIError(f"Failed to get license. Status: {response.status_code}")
            
            license_data = response.json()
            if not license_data.get('success') or 'data' not in license_data:
                raise PWAPIError("Invalid response from license API")
            
            key = self.get_key_final(license_data['data']['otp'])
            
            return full_url, key, self.cookies
            
        except Exception as e:
            raise PWAPIError(f"Error getting video URL and key: {str(e)}")

    def get_video_url_and_key_from_direct_link(self, mpd_url: str) -> Tuple[str, str, str]:
        """Get decryption key for direct MPD URL"""
        try:
            # Extract KID from MPD
            kid = self.extract_kid_from_mpd(mpd_url)
            if not kid:
                raise PWAPIError("Could not extract KID from MPD")
            
            kid_clean = kid.replace("-", "")
            
            # Get decryption key
            otp_key = self.b64_encode(self.xor_encrypt(kid_clean))
            encoded_otp_key_step1 = otp_key.encode('utf-8').hex()
            encoded_otp_key = self.insert_zeros(encoded_otp_key_step1)
            
            license_url = self.build_license_url(encoded_otp_key)
            headers = self.get_otp_headers()
            
            response = requests.get(license_url, headers=headers)
            if response.status_code != 200:
                raise PWAPIError(f"Failed to get license. Status: {response.status_code}")
            
            license_data = response.json()
            if not license_data.get('success') or 'data' not in license_data:
                raise PWAPIError("Invalid response from license API")
            
            key = self.get_key_final(license_data['data']['otp'])
            
            # Extract cookies from URL if present
            self.cookies = self._extract_cookies_from_url(mpd_url)
            
            return mpd_url, key, self.cookies
            
        except Exception as e:
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

    def load_and_parse(self) -> Dict:
        """Load and parse MPD manifest"""
        try:
            response = requests.get(self.url)
            if response.status_code != 200:
                raise PWAPIError(f"Failed to load MPD manifest. Status: {response.status_code}")
            
            self.mpd_dict = xmltodict.parse(response.text, process_namespaces=False)
            return self.mpd_dict
        except Exception as e:
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
            return qualities
            
        except Exception as e:
            raise PWAPIError(f"Error extracting qualities: {str(e)}")

    def get_segment_urls(self, target_height: Optional[int] = None) -> Dict:
        """Extract all segment URLs for audio and video with quality selection"""
        if not self.mpd_dict:
            self.load_and_parse()
        
        try:
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
                        else:
                            # Default to highest quality
                            best_rep = max(representations, 
                                         key=lambda x: int(x.get("@height", "0")))
                        representation = best_rep
                    else:
                        representation = representations[0]
                    
                    segment_template = representation.get("SegmentTemplate", {})
                    
                    # Get init URL
                    init_template = segment_template.get("@initialization", "")
                    if init_template:
                        result[content_type]['init'] = self.build_url(init_template)
                    
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
                    
                    # Generate segment URLs
                    for i in range(start_number, segment_count + 1):
                        result[content_type]['segments'][i] = self.build_url(media_template, i)
            
            return result
            
        except Exception as e:
            raise PWAPIError(f"Error extracting segment URLs: {str(e)}")