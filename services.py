from fastapi import Request, HTTPException, status
from twilio.request_validator import RequestValidator
import os
from twilio.rest import Client
from typing import List, TypedDict, Literal
import hmac
import hashlib
import io
from loguru import logger
from urllib.parse import unquote
from tenacity import retry, wait_random_exponential, stop_after_attempt

twilio_client = None

class HistoryMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str

if ("VOICECALL_ACCOUNT_SID" in os.environ) and ("VOICECALL_AUTH_TOKEN" in os.environ):
    account_sid = os.environ.get('VOICECALL_ACCOUNT_SID')
    auth_token = os.environ.get('VOICECALL_AUTH_TOKEN')
    twilio_client = Client(account_sid, auth_token)
else:
    print("No Voice calling available for the tenant.")
    
def get_twilio_client():
    return Client(account_sid, auth_token)

async def validate_request(request: Request) -> bool:
    """
    This function validates the if the request is coming from Twilio, if the request is valid it also adds parameters parsed from the form in the request body to request.state.body

        Parameters:
            request (Request): The request object from FastAPI
    """
    headers = request.headers
    signature = headers.get("X-Twilio-Signature")
    VOICECALL_AUTH_TOKEN = os.environ.get("VOICECALL_AUTH_TOKEN")
    if not signature or not VOICECALL_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Extract the form data from the request
    body = await request.form()
    # Initialize the validator
    validator = RequestValidator(VOICECALL_AUTH_TOKEN)
    # Validating if request is made by Twilio, else reject it
    url = f'https://{request.headers["Host"]}{request.url.path}'
    if request.query_params:
        url = f'{url}?{unquote(str(request.query_params))}'
    if not validator.validate(url, body, signature):
        raise HTTPException(status_code=401, detail="Unauthorized")
    else:
        request.state.body = body
        return True
        
def generate_websocket_signature(chat_id: str, call_sid: str, mobile: str) -> str:
    """Generates websocket signature for the given chat_id, call_sid and mobile
    
        Args:
            chat_id (str): Chat id
            call_sid (str): Unique call id from Twilio
            mobile (str): Mobile number of the user
        
        Returns:
            (str): The websocket signature"""
    if not chat_id or not call_sid or not mobile:
        raise Exception("chat_id, call_sid and mobile are required")
    
    signature = os.getenv('WEBSOCKET_SIGNATURE')
    if not signature:
        raise Exception("WEBSOCKET_SIGNATURE is not set")
    
    data = f"chat_id={chat_id}&call_sid={call_sid}&mobile={mobile}"
    result = hmac.new(signature.encode(), data.encode(), hashlib.sha1).hexdigest()
    return result

def verify_websocket_signature(chat_id: str, call_sid: str, mobile: str, signature: str):
    """Verifies websocket signature for the given chat_id, call_sid and mobile
    
        Args:
            chat_id (str): Chat id
            call_sid (str): Unique call id from Twilio
            mobile (str): Mobile number of the user
            signature (str): The signature to verify
        
        Returns:
            (bool): True if the signature is valid, False otherwise"""
    if not chat_id or not call_sid or not mobile:
        raise Exception("chat_id, call_sid and mobile are required")
    
    if not signature:
        raise Exception("Signature is required")
    
    expected_signature = generate_websocket_signature(chat_id=chat_id, call_sid=call_sid, mobile=mobile)
    return hmac.compare_digest(expected_signature, signature)
