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



# Learned about enums here: https://docs.python.org/3/library/enum.html
from enum import Enum

NetProtocol = Enum("NetProtocol", ["ILNP", "IPv6"], start=0)

HeaderSizes = {
    "TRANSPORT":12,
    "ILNP":40,
    "LINK":24,
    "NEIGHBOUR_AD": 24,
    "ROUTER_AD": 16,
    "LOCATOR_UPDATE": 16
}
LUAction = Enum("LUAction", ["ILNP_LU_ADD_HARD",
                             "ILNP_LU_ADD_SOFT",
                             "ILNP_LU_DELETE_HARD",
                             "ILNP_LU_DELETE_SOFT",
                             "ILNP_LU_REPLACE_HARD",
                             "ILNP_LU_REPLACE_SOFT"], start=2)

LUOperation = Enum("LUOperation", ["ILNP_LU_AD",
                                   "ILNP_LU_ACK"], start=0)

LocatorFlag = Enum("LocatorFlag", ["ACTIVE",
                                   "VALID_JOIN",
                                   "VALID_LEAVE",
                                   "AGED",
                                   "EXPIRED"], start=0)

ControlPacketType = Enum("ControlPacketType", ["ROUTER_AD",
                                               "NEIGHBOUR_AD",
                                               "LOCATOR_UPDATE",
                                               "ROUTER_SOL",
                                               "NEIGHBOUR_SOL"], start=0)

APICommandCode = Enum("APICommandCode", ["ID",
                                           "IS_ROUTER",
                                           "SEND",
                                           "RECV",
                                           "CREATE_SOCK",
                                           "CLOSE_SOCK",
                                           "JOIN",
                                           "LEAVE",
                                           "QUIT",
                                           "FLOOD",
                                           "REPLACE",
                                           "GET",
                                           "START_IOT_DEVICE",
                                           "GET_VALUE",
                                            "HANDSHAKE",
                                         "HANDSHAKE_REPLY",
                                         "CANCEL",
                                         "HAS_DATA"
                                           ], start=0)

NextHeader = Enum("NextHeader", ["CONTROL",
                                   "TRANSPORT"], start=0)

UDP_MAX_SIZE = 65535

GetCommandIndex = Enum("GetCommandIndex", ["ILV_CACHE",
                                               "ALL_LOCS",
                                               "AVAILABLE_ROUTERS",
                                               "FORWARDING_TABLE",
                                               "CORRESPONDENTS",
                                           "INV_LOCS"], start=0)

ValueIndex = Enum("ValueIndex", ["ID", "IS_ROUTER", "CPU_TIME", "RSS", "VIRTUAL_MEM", "OVERHEAD", "RUNTIME"], start=0)

required_configs = {'correspondents_timeout', 'remote_loc_aged_timeout', 'max_locs', 'forwarding_entry_timeout', 'BROADCAST_IDENTIFIER', 'own_loc_active_timeout', 'own_loc_aged_timeout', 'lu_resend_interval', 'neighbour_ad_interval', 'remote_loc_active_timeout', 'SCOPE_ID', 'mgmt_port', 'FLOW_INFO', 'delay', 'purge_rate_limit', 'BROADCAST_LOC', 'remote_loc_expired_timeout', 'startup_wait', 'router_ad_interval', 'QUANTUM', 'available_router_timeout', 'last_used_timeout', 'emulation_port', 'transport_mss', 'mcast_prefix'}


SERVER="server"
HANDLER="handler"
RUNNER="runner"