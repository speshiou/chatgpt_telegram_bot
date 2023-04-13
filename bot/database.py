from datetime import datetime
from typing import Any

import pymongo
from bson.objectid import ObjectId

import config


class Database:
    def __init__(self):
        self.client = pymongo.MongoClient(config.MONGODB_URI)
        self.db = self.client["chatgpt_telegram_bot"]

        self.user_collection = self.db["users"]
        self.chat_collection = self.db["chats"]
        self.dialog_collection = self.db["dialogs"]
        self.stat_collection = self.db["stats"]

    def check_if_user_exists(self, user_id: int, raise_exception: bool = False):
        if self.user_collection.count_documents({"_id": user_id}) > 0:
            return True
        else:
            if raise_exception:
                raise ValueError(f"User {user_id} does not exist")
            else:
                return False
        
    def add_new_user(
        self,
        user_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
        referred_by: int = None,
    ):
        data = {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,

            "last_interaction": datetime.now(),
            "first_seen": datetime.now(),

            "used_tokens": 0,
            "total_tokens": config.FREE_QUOTA,

            "referred_by": referred_by,
            "referred_count": 0,
        }

        query = {"_id": user_id}
        update = {
            "$setOnInsert": data,
        }

        self.user_collection.update_one(query, update, upsert=True)

    def upsert_chat(self, chat_id: int, dialog_id: ObjectId, chat_mode=config.DEFAULT_CHAT_MODE):
        default_data = {
            "first_seen": datetime.now(),
            "used_tokens": 0,
        }

        data = {
            "current_chat_mode": chat_mode,
            "current_dialog_id": dialog_id,
            "last_interaction": datetime.now(),
        }

        query = {"_id": chat_id}
        update = {
            "$set": data,
            "$setOnInsert": default_data,
        }

        self.chat_collection.update_one(query, update, upsert=True)

    def get_chat_attribute(self, chat_id: int, key: str):
        data = self.chat_collection.find_one({"_id": chat_id})
        return data[key] if data and key in data else None

    def get_current_chat_mode(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'current_chat_mode') or config.DEFAULT_CHAT_MODE

    def get_chat_dialog_id(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'current_dialog_id')

    def start_new_dialog(self, chat_id: int, chat_mode=None):
        chat_mode = chat_mode or self.get_current_chat_mode(chat_id)
        dialog_id = ObjectId()
        dialog_dict = {
            "_id": dialog_id,
            "chat_id": chat_id,
            "chat_mode": chat_mode,
            "start_time": datetime.now(),
            "messages": []
        }

        # add new dialog
        self.dialog_collection.insert_one(dialog_dict)

        # update chat dialog
        self.upsert_chat(chat_id, dialog_id, chat_mode)

        return dialog_id
    
    def get_dialog_messages(self, chat_id: int):
        dialog_id = self.get_chat_dialog_id(chat_id)
        if not dialog_id:
            return None
        dialog_dict = self.dialog_collection.find_one({"_id": dialog_id, "chat_id": chat_id})               
        return dialog_dict["messages"] if dialog_dict else None

    def pop_dialog_messages(self, chat_id: int):
        dialog_id = self.get_chat_dialog_id(chat_id)
        
        self.dialog_collection.update_one(
            {"_id": dialog_id, "chat_id": chat_id},
            {"$pop": {"messages": 1}}
        )

    def push_dialog_messages(self, chat_id: int, new_dialog_message, max_message_count: int=-1):
        dialog_id = self.get_chat_dialog_id(chat_id)

        if max_message_count > 0:
            self.dialog_collection.update_one(
                {"_id": dialog_id, "chat_id": chat_id},
                {"$push": {"messages": {
                    "$each": [ new_dialog_message ],
                    "$slice": -max_message_count,
                }}}
            )
        else:
            self.dialog_collection.update_one(
                {"_id": dialog_id, "chat_id": chat_id},
                {"$push": {"messages": new_dialog_message}}
            )

    def get_user_attribute(self, user_id: int, key: str):
        self.check_if_user_exists(user_id, raise_exception=True)
        return self.get_user_attributes(user_id, [key])[0]
    
    def get_user_attributes(self, user_id: int, keys: list):
        self.check_if_user_exists(user_id, raise_exception=True)
        user_dict = self.user_collection.find_one({"_id": user_id})

        ret = []
        for key in keys:
            if key not in user_dict:
                raise ValueError(f"User {user_id} does not have a value for {key}")
            ret.append(user_dict[key] if key in user_dict else None)

        return ret
    
    def get_user_preferred_language(self, user_id: int):
        try:
            return self.get_user_attribute(user_id, 'preferred_lang')
        except:
            return None
    
    def get_user_remaining_tokens(self, user_id: int):
        total_tokens, used_tokens = self.get_user_attributes(user_id, ['total_tokens', 'used_tokens'])
        return total_tokens - used_tokens

    def inc_user_referred_count(self, user_id: int):
        self.user_collection.update_one({"_id": user_id}, {"$inc": { 'referred_count': 1}})

    def inc_user_used_tokens(self, user_id: int, used_token: int):
        self.user_collection.update_one({"_id": user_id}, {"$inc": { 'used_tokens': used_token}})

    def is_user_generating_image(self, user_id: int):
        try:
            timeout = config.IMAGE_TIMEOUT
            last_imaging_time = self.get_user_attribute(user_id, 'last_imaging_time')
            diff = (datetime.now() - last_imaging_time).total_seconds()
            if last_imaging_time is None or diff > timeout:
                return False
            return timeout - diff
        except Exception as e:
            pass
        return False
    
    def mark_user_is_generating_image(self, user_id: int, generating: bool):
        self.set_user_attribute(user_id, 'last_imaging_time', datetime.now() if generating else None)

    def set_user_attribute(self, user_id: int, key: str, value: Any):
        self.check_if_user_exists(user_id, raise_exception=True)
        self.user_collection.update_one({"_id": user_id}, {"$set": {key: value}})

    def inc_stats(self, field: str, amount: int = 1):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        default_data = { 
            "new_users": 0,
            "referral_new_users": 0,
        }

        if field not in default_data:
            raise ValueError(f"Invalid field `{field}` for stats")
        
        # prevent conflict field
        default_data.pop(field, None)

        inc = { field: amount }

        query = {"_id": today}
        update = {
            "$setOnInsert": default_data,
            "$inc": inc,
        }

        self.stat_collection.update_one(query, update, upsert=True)

