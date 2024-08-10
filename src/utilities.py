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


import struct
import socket
import time
import os
import math
import asyncio
import uuid
from ILNPReceiverProtocol import ILNPReceiverProtocol
from constants import *

"""
Utility methods including:
    Methods to get and decode emulation packet headers
    Creating identifiers and locators from underlying device's MAC address
    Getting the multicast address from the corresponding locator
    Getting an asycnronous datagram endpoint which listens on a multicast address
"""

def get_router_ad(locs, ad_no, router_id):
    router_ad = struct.pack("BB2xIQ", ControlPacketType.ROUTER_AD.value, len(locs), ad_no, router_id)

    for loc in locs:
        router_ad += struct.pack("Q", loc)

    return router_ad


def decode_router_ad(router_ad):
    decoded_router_ad = {"type": router_ad[0], "ad_no": int.from_bytes(router_ad[4:8], "little"),
                         "id": int.from_bytes(router_ad[8:16], "little")}

    num_of_locs = router_ad[1]

    locs = []
    for start in range(16, 16 + num_of_locs * 8, 8):
        locs.append(int.from_bytes(router_ad[start:start + 8], "little"))

    decoded_router_ad["locs"] = locs

    return decoded_router_ad


def get_neighbour_ad(locs, ad_no, neighbour_id, is_router, loc_set_no):
    neighbour_ad = struct.pack("BBHH2xIIQ", ControlPacketType.NEIGHBOUR_AD.value, int(is_router), len(locs), 0, ad_no,
                               loc_set_no, neighbour_id)

    for loc in locs:
        neighbour_ad += struct.pack("Q", loc)

    return neighbour_ad


def decode_neighbour_ad(neighbour_ad):
    decoded_neighbour_ad = {"type": neighbour_ad[0], "is_router": int.from_bytes(neighbour_ad[1:2], "little") == 1,
                            "hops": int.from_bytes(neighbour_ad[4:6], "little"),
                            "ad_no": int.from_bytes(neighbour_ad[8:12], "little"),
                            "loc_set_no": int.from_bytes(neighbour_ad[12:16], "little"),
                            "id": int.from_bytes(neighbour_ad[16:24], "little")}

    num_of_locs = int.from_bytes(neighbour_ad[2:4], "little")

    locs = []
    for start in range(24, 24 + num_of_locs * 8, 8):
        locs.append(int.from_bytes(neighbour_ad[start:start + 8], "little"))

    decoded_neighbour_ad["locs"] = locs

    return decoded_neighbour_ad


def get_router_sol(router_sol_no):
    return struct.pack("BB", ControlPacketType.ROUTER_SOL.value, router_sol_no)


def decode_router_sol(router_sol):
    return {"code": router_sol[0], "router_sol_no": router_sol[1]}


def get_neighbour_sol(neighbour_id, neighbour_sol_no):
    return struct.pack("BB6xQ", ControlPacketType.NEIGHBOUR_SOL.value, neighbour_sol_no, neighbour_id)


def decode_neighbour_sol(neighbour_sol):
    return {"code": neighbour_sol[0], "neighbour_sol_no": neighbour_sol[1], "neighbour_id": int.from_bytes(neighbour_sol[8:16], "little")}


def get_transport_dgram(src_port, dst_port, flood_no, payload):
    return struct.pack("III", src_port, dst_port, flood_no) + payload


def decode_transport_dgram(transport_dgram):
    decoded_transport_dgram = {"src_port": int.from_bytes(transport_dgram[0:4], "little"),
                               "dst_port": int.from_bytes(transport_dgram[4:8], "little"),
                               "flood_no": int.from_bytes(transport_dgram[8:12], "little"),
                               "payload": transport_dgram[12:]}
    return decoded_transport_dgram

def get_ilnp_dgram(next_hdr, src_id, src_loc, dst_id, dst_loc, payload, is_router):
    return struct.pack("BB6xQQQQ", next_hdr, int(is_router), src_id, src_loc, dst_id, dst_loc) + payload


def decode_ilnp_dgram(ilnp_dgram):
    decoded_ilnp_dgram = {"next_hdr": ilnp_dgram[0], "src_id": int.from_bytes(ilnp_dgram[8:16], "little"),
                          "is_router": ilnp_dgram[1] == 1,
                          "src_loc": int.from_bytes(ilnp_dgram[16:24], "little"),
                          "dst_id": int.from_bytes(ilnp_dgram[24:32], "little"),
                          "dst_loc": int.from_bytes(ilnp_dgram[32:40], "little"), "payload": ilnp_dgram[40:]}

    return decoded_ilnp_dgram


def get_link_frame(src_id, dst_id, loc, payload):
    return struct.pack("QQQ", src_id, dst_id, loc) + payload


def decode_link_frame(link_frame):
    decoded_link_frame = {"src_id": int.from_bytes(link_frame[0:8], "little"),
                          "dst_id": int.from_bytes(link_frame[8:16], "little"),
                          "loc": int.from_bytes(link_frame[16:24], "little"), "payload": link_frame[24:]}
    return decoded_link_frame


def get_locator_update(action, op, locs, loc_set_no, id):
    locator_update = struct.pack("BBBBIQ", ControlPacketType.LOCATOR_UPDATE.value, action, len(locs), op, loc_set_no, id)

    for loc in locs:
        locator_update += struct.pack("Q", loc)

    return locator_update


def decode_locator_update(locator_update):
    decoded_lu = {"type": locator_update[0], "action": locator_update[1], "operation": locator_update[3],
                  "loc_set_no": int.from_bytes(locator_update[4:8], "little"),
                  "id": int.from_bytes(locator_update[8:16], "little")}

    num_of_locs = locator_update[2]

    locs = []
    for start in range(16, 16 + num_of_locs * 8, 8):
        locs.append(int.from_bytes(locator_update[start:start + 8], "little"))

    decoded_lu["locs"] = locs

    return decoded_lu


def get_lu_ack(lu):
    ba = bytearray(lu)
    ba[5] = LUOperation.ILNP_LU_ACK.value
    return bytes(ba)


def locator_to_mcast(locator, mcast_prefix):
    """Converts locator value to multicast address starting with the passed multicast prefix"""
    prefix = bytes.fromhex(mcast_prefix.replace(":", ""))

    return socket.inet_ntop(socket.AF_INET6, prefix + locator.to_bytes(8, "big"))


def get_identifier():
    """Get Identifier value using last 64 bits of IPv6 address which is unique in this network"""

    # Learned to get MAC address here
    # https://www.geeksforgeeks.org/extracting-mac-address-using-python/

    mac_bytes = int.to_bytes(uuid.getnode(), 6, "big")
    mac_bytes += int.to_bytes(0, 2, "big")
    return int.from_bytes(mac_bytes, "big")


def get_locators(no_of_locs):
    """Get locator values using last 64 bits of IPv6 address which is unique in this network"""

    # Learned to get MAC address here
    # https://www.geeksforgeeks.org/extracting-mac-address-using-python/

    locators = []

    mac_bytes = int.to_bytes(uuid.getnode(), 6, "big")



    for i in range(no_of_locs):
        loc_bytes = mac_bytes + int.to_bytes(i, 2, "big")

        locators.append(int.from_bytes(loc_bytes, "big"))


    return locators


async def get_loc_transport(loc, mcast_prefix, process_dgram, flow_info, scope_id):
    # code adapted from here: https://svn.python.org/projects/python/trunk/Demo/sockets/mcast.py

    # Create a socket
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    # Get bytes of multicast address passed in constructor
    addrinfo = socket.getaddrinfo(locator_to_mcast(loc, mcast_prefix), None)[0]
    group_bin = socket.inet_pton(socket.AF_INET6, addrinfo[4][0])

    # Unsigned int used as that is what is used in mreq object.
    mreq = group_bin + struct.pack('@I', scope_id)

    # Join multicast group
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq)

    # Bind it to the port, '' represents :: which is any IPv6 interface, 2 represents the interface label for the
    # ethernet interface on the lab clients which is connected correctly so it works
    sock.bind((addrinfo[4][0], os.getuid(), flow_info, scope_id))

    # Got the code that creates a datagram endpoint to allow asynchronous network programming here: https://docs.python.org/3/library/asyncio-protocol.html
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    # One protocol instance will be created to serve all
    # client requests.
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: ILNPReceiverProtocol(process_dgram),
        sock=sock)

    return transport


def flag_to_string(flag):
    flags_to_strings = {LocatorFlag.ACTIVE.value: "ACTIVE", LocatorFlag.VALID_JOIN.value: "VALID_JOIN",
                        LocatorFlag.VALID_LEAVE.value: "VALID_LEAVE", LocatorFlag.AGED.value: "AGED",
                        LocatorFlag.EXPIRED.value: "EXPIRED"}

    if flag not in flags_to_strings:
        raise Exception("Invalid flag passed to flag_to_string(flag)")

    return flags_to_strings[flag]

def validate_settings_dict(settings_dict):
    """Ensure the settings dict contains all the required parameters"""
    return required_configs.issubset(settings_dict.keys())