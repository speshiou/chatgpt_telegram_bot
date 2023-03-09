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
        chat_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ):
        user_dict = {
            "_id": user_id,
            "chat_id": chat_id,

            "username": username,
            "first_name": first_name,
            "last_name": last_name,

            "last_interaction": datetime.now(),
            "first_seen": datetime.now(),
            
            "current_dialog_id": None,
            "current_chat_mode": "assistant",

            "used_tokens": 0,
            "total_tokens": config.FREE_QUOTA,
        }

        if not self.check_if_user_exists(user_id):
            self.user_collection.insert_one(user_dict)
            
        # TODO: maybe start a new dialog here?

    def start_new_dialog(self, user_id: int):
        self.check_if_user_exists(user_id, raise_exception=True)

        dialog_id = ObjectId()
        dialog_dict = {
            "_id": dialog_id,
            "user_id": user_id,
            "chat_mode": self.get_user_attribute(user_id, "current_chat_mode"),
            "start_time": datetime.now(),
            "messages": []
        }

        # add new dialog
        self.dialog_collection.insert_one(dialog_dict)

        # update user's current dialog
        self.user_collection.update_one(
            {"_id": user_id},
            {"$set": {"current_dialog_id": dialog_id}}
        )

        return dialog_id

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
            ret.append(user_dict[key])

        return ret
    
    def get_user_preferred_language(self, user_id: int):
        try:
            return self.get_user_attribute(user_id, 'preferred_lang')
        except:
            return None
    
    def get_user_remaining_tokens(self, user_id: int):
        total_tokens, used_tokens = self.get_user_attributes(user_id, ['total_tokens', 'used_tokens'])
        return total_tokens - used_tokens

    def inc_user_used_tokens(self, user_id: int, used_token: int):
        self.user_collection.update_one({"_id": user_id}, {"$inc": { 'used_tokens': used_token}})

    def set_user_attribute(self, user_id: int, key: str, value: Any):
        self.check_if_user_exists(user_id, raise_exception=True)
        self.user_collection.update_one({"_id": user_id}, {"$set": {key: value}})

    def get_dialog_messages(self, user_id: int):
        self.check_if_user_exists(user_id, raise_exception=True)

        dialog_id = self.get_user_attribute(user_id, "current_dialog_id")
        dialog_dict = self.dialog_collection.find_one({"_id": dialog_id, "user_id": user_id})               
        return dialog_dict["messages"] if dialog_dict else None

    def set_dialog_messages(self, user_id: int, dialog_messages: list):
        self.check_if_user_exists(user_id, raise_exception=True)

        dialog_id = self.get_user_attribute(user_id, "current_dialog_id")
        
        self.dialog_collection.update_one(
            {"_id": dialog_id, "user_id": user_id},
            {"$set": {"messages": dialog_messages}}
        )

    def inc_stats(self, field: str, amount: int = 1):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        default_data = { 
            "new_users": 0,
            "referral_new_users": 0,
            "net_sales": 0, 
            "new_orders": 0,
            "paid_orders": 0,
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

