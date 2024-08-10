# Copyright 2023 Daniel Vallance
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


from animal_tracker_constants import *
import struct
import time
import math

def get_tracking_request_dgram(req_no):
    return struct.pack("B3xI",REQUEST, req_no)

def decode_tracking_request_dgram(tracking_request_dgram):
    return {"code": tracking_request_dgram[0], "req_no": int.from_bytes(tracking_request_dgram[4:8], "little")}


def get_tracking_response_dgram(req_no, router_id):
    tracking_response_dgram = struct.pack("B3xIQ",RESPONSE,req_no,router_id)
    return tracking_response_dgram

def decode_tracking_response_dgram(tracking_response_dgram):
    return {"code": tracking_response_dgram[0], "req_no": int.from_bytes(tracking_response_dgram[4:8], "little"), "router_id": int.from_bytes(tracking_response_dgram[8:16], "little")}