import os
import time
import requests
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

def create(user_id, payment_method, price, token_amount):
    params = {
        'tg_user_id': user_id,
        'payment_method': payment_method,
        'payment_amount': price,
        'token_amount': token_amount,
        'create_time': int(time.time()),
    }
    hash = hash_query(params)
    params['hash'] = hash
    query_params = ''
    for key, value in params.items():
        query_params += f'{key}={value}&'
    query_params = query_params[:-1] # Remove the last '&'
    full_url = f'{config.PAYMENT_ENDPOINT}?{query_params}'
    response = requests.get(full_url)
    try:
        return response.json()
    except Exception as e:
        print(response)
        print(e)
    return None
