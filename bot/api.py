import os
import time
import aiohttp
import hashlib
import hmac

import config

def hash_query(params):
    data_check_arr = []
    for key, value in params.items():
        data_check_arr.append(f'{key}={value}')
    data_check_arr.sort()
    data_check_string = '\n'.join(data_check_arr)
    secret_key = hashlib.sha256(config.TELEGRAM_BOT_TOKEN.encode()).digest()
    hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hash

async def api_request(endpoint, params):
    if not config.API_ENDPOINT:
        return None
    url = os.path.join(config.API_ENDPOINT, endpoint)

    params['create_time'] = int(time.time())
    hash = hash_query(params)
    params['hash'] = hash
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                response_data = await response.json()
                return response_data
            else:
                # handle error response
                return None


async def create_order(user_id, payment_method, price, token_amount):
    params = {
        'tg_user_id': user_id,
        'payment_method': payment_method,
        'payment_amount': price,
        'token_amount': token_amount,
    }
    
    return await api_request("orders/create", params)

async def earn(user_id):
    params = {
        'tg_user_id': user_id,
    }
    
    return await api_request("earn", params)
