from urllib.parse import urlencode, quote
import os
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Refer
import json
from loguru import logger

def transfer_call_to_agent(call_sid: str, chat_id: str, sip_uui_header: str = None):
    """Transfers calls to provided destination sip address, this is specific to sip calls only
    
    Parameters:
        call_sid (str): Unique call sid from Twilio
        destination_address (str): Destination sip address
        sip_uui_header (str): SIP uui header value
    """
    flag_destination_address = os.environ.get('SIP_TRANSFER_URL', "sip:tester@testing2.sip.twilio.com")
    if flag_destination_address:
        destination_address = flag_destination_address
    # destination_address = "sip:tester@testing2.sip.twilio.com"
    # destination_address = "sip:17056@208.163.53.129"
    print("call_sid: ", call_sid, "\ndestination_address: ", destination_address, "\nsip_uui_header: ", "sip_uui_header")
    account_sid = os.environ.get('VOICECALL_ACCOUNT_SID')
    auth_token = os.environ.get('VOICECALL_AUTH_TOKEN')
    twilio_client = Client(account_sid, auth_token)
    # headers = f"User-to-User=asdbgi142;transport=tcp"
    # headers = f"User-to-User={sip_uui_header};transport=tls"
    # headers = f"Refer-to={destination_address};transport=tcp"
    # headers = f"Refer-to={destination_address};transport=tls"
    headers = f"transport=udp"
    response = VoiceResponse()

    host_url = os.environ['HOST']
    # callback is added this will receive status update for the transfer if it was successfull or not
    refer = Refer(
        action=f"{host_url}/webhook/refer-callback?chat_id={chat_id}&destination_address={destination_address}", method="POST"
    )
    refer.sip(f"{destination_address}?{headers}")
    # refer.sip(f"{destination_address}")
    response.append(refer)
    logger.info(response)
    twilio_client.calls(call_sid).update(twiml=str(response))
