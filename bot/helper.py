import re
import aiohttp
from urllib.parse import urlparse

async def http_post(url, data, result_type="json"):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as response:
            if result_type == "json":
                return await response.json()
            else:
                return await response.text()

def is_uri(s):
    try:
        result = urlparse(s)
        return all([result.scheme, result.netloc])
    except:
        return False

def is_youtube_url(url: str):
    domain = urlparse(url).netloc
    return domain.endswith("youtube.com") or domain.endswith("youtu.be")

def parse_youtube_id(url: str)->str:
   data = re.findall(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
   if data:
       return data[0]
   return ""