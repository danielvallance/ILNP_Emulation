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


import math
import time
from tsn_constants import *
import struct


def get_temp_dgram(temp, seq_no):
    now = time.time_ns()
    return struct.pack("IIQ", temp, seq_no, int(now/1000000))


def decode_temp_dgram(temp_dgram):
    return {"temp": int.from_bytes(temp_dgram[0:4], "little"),
                          "seq_no": int.from_bytes(temp_dgram[4:8], "little"),
                          "milliseconds": int.from_bytes(temp_dgram[8:16], "little")}

def get_register_interest_dgram(lower, upper, seq_no):
    return struct.pack("BBBxI", TsnMessage.REGISTER_INTEREST.value,lower, upper, seq_no)

def decode_register_interest_dgram(sink_register_dgram):
    decoded_sink_register_dgram = {}
    decoded_sink_register_dgram["code"] = sink_register_dgram[0]
    decoded_sink_register_dgram["lower"] = sink_register_dgram[1]
    decoded_sink_register_dgram["upper"] = sink_register_dgram[2]
    decoded_sink_register_dgram["seq_no"] = int.from_bytes(sink_register_dgram[4:8], "little")

    return decoded_sink_register_dgram