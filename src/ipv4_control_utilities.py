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



from constants import *
import struct

"""
File containing dictionaries and functions used in control plane communication

The functions are mostly encoders and decoders of API commands
"""

# Sizes of each API command packet in bytes
cmd_sizes = {
    APICommandCode.QUIT.value: 1,
    APICommandCode.IS_ROUTER.value: 1,
    APICommandCode.ID.value: 1,
    APICommandCode.GET.value: 2,
    APICommandCode.SEND.value: 24,
    APICommandCode.RECV.value: 8,
    APICommandCode.CREATE_SOCK.value: 8,
    APICommandCode.CLOSE_SOCK.value: 8,
    APICommandCode.JOIN.value: 8,
    APICommandCode.LEAVE.value: 8,
    APICommandCode.FLOOD.value: 16,
    APICommandCode.REPLACE.value: 8,
    APICommandCode.START_IOT_DEVICE.value: 3,
    APICommandCode.GET_VALUE.value: 2,
    APICommandCode.HANDSHAKE.value: 1,
    APICommandCode.HANDSHAKE_REPLY.value: 2,
    APICommandCode.CANCEL.value: 1,
    APICommandCode.HAS_DATA.value: 8

}

# Bytes required to represent the corresponding items of the emulation's state
VALUE_SIZES = {
    ValueIndex.ID.value: 8,
    ValueIndex.IS_ROUTER.value: 1,
    ValueIndex.CPU_TIME.value: 8,
    ValueIndex.RSS.value: 8,
    ValueIndex.VIRTUAL_MEM.value: 8,
    ValueIndex.OVERHEAD.value: 32,
    ValueIndex.RUNTIME.value: 8
}


# General encoder of command to get an object (not a value)
def get_get_command(item_index):
    return struct.pack("BB", APICommandCode.GET.value, item_index)


def decode_get_command(get_command):
    return {"code": get_command[0], "item_index": get_command[1]}

# General encoder of command to get a value (not an object)
def get_get_value_command(value_index):
    return struct.pack("BB", APICommandCode.GET_VALUE.value, value_index)


def decode_get_value_command(get_value_cmd):
    return {"code": get_value_cmd[0], "value_index": get_value_cmd[1]}

# General encoder of single byte commands
def get_noarg_command(code):
    return struct.pack("B", code)


def decode_noarg_command(noarg_command):
    return {"code": noarg_command[0]}


def get_locs_command():
    return get_get_command(APICommandCode.LOCS.value)


def get_quit_command():
    return get_noarg_command(APICommandCode.QUIT.value)


def get_ilv_cache_command():
    return get_get_command(APICommandCode.ILV_CACHE.value)


def get_forwarding_table_command():
    return get_get_command(APICommandCode.FORWARDING_TABLE.value)


def get_correspondents_command():
    return get_get_command(APICommandCode.CORRESPONDENTS.value)


def get_available_routers_command():
    return get_get_command(APICommandCode.AVAILABLE_ROUTERS.value)


def get_send_command(dst_id, src_port, dst_port, data):
    return struct.pack("B3xIIIQ", APICommandCode.SEND.value, len(data), src_port, dst_port, dst_id) + data


def decode_send_command(send_cmd):
    return {"code": send_cmd[0], "data_length": int.from_bytes(send_cmd[4:8], "little"),
            "src_port": int.from_bytes(send_cmd[8:12], "little"),
            "dst_port": int.from_bytes(send_cmd[12:16], "little"),
            "id": int.from_bytes(send_cmd[16:24], "little"), "data": send_cmd[24:]}


def get_recv_command(port):
    return struct.pack("B3xI", APICommandCode.RECV.value, port)


def decode_recv_command(recv_cmd):
    return {"code": recv_cmd[0], "port": int.from_bytes(recv_cmd[4:8], "little")}


def get_flood_command(src_port, dst_port, data):
    flood_cmd = struct.pack("B3xIII", APICommandCode.FLOOD.value, src_port, dst_port, len(data))
    flood_cmd += data
    return flood_cmd


def decode_flood_command(flood_cmd):
    return {"code": flood_cmd[0], "src_port": int.from_bytes(flood_cmd[4:8], "little"),
            "dst_port": int.from_bytes(flood_cmd[8:12], "little"),
            "data_length": int.from_bytes(flood_cmd[12:16], "little"),
            "data": flood_cmd[16:]}


def get_sock_cmd(code, port):
    return struct.pack("B3xI", code, port)


def get_create_sock_cmd(port):
    return get_sock_cmd(APICommandCode.CREATE_SOCK.value, port)


def get_close_sock_cmd(port):
    return get_sock_cmd(APICommandCode.CLOSE_SOCK.value, port)


def decode_sock_command(sock_cmd):
    return {"code": sock_cmd[0], "port": int.from_bytes(sock_cmd[4:8], "little")}


def get_lu_command(code, locs):
    lu_cmd = struct.pack("BB6x", code, len(locs))

    for loc in locs:
        lu_cmd += struct.pack("Q", loc)

    return lu_cmd


def decode_lu_command(lu_cmd):
    return {"code": lu_cmd[0], "no_of_locs": lu_cmd[1]}

def get_join_command(locs):
    return get_lu_command(APICommandCode.JOIN.value, locs)


def get_leave_command(locs):
    return get_lu_command(APICommandCode.LEAVE.value, locs)


def get_replace_command(locs):
    return get_lu_command(APICommandCode.REPLACE.value, locs)


def get_start_iot_device_command(no_inv_locs, net_protocol):
    start_iot_device_cmd = struct.pack("BbB", APICommandCode.START_IOT_DEVICE.value,
                                       no_inv_locs, net_protocol)

    return start_iot_device_cmd


def decode_start_iot_device_command(start_iot_device_cmd):
    decoded_start_iot_device_command = {"code": start_iot_device_cmd[0],
                                        "no_inv_locs": int.from_bytes(start_iot_device_cmd[1:2], "little", signed=True),
                                        "net_protocol": start_iot_device_cmd[2]}

    return decoded_start_iot_device_command


def get_handshake_command():
    return struct.pack("B", APICommandCode.HANDSHAKE.value)

def get_handshake_reply(available):
    return struct.pack("BB", APICommandCode.HANDSHAKE_REPLY.value, int(available))

def decode_handshake_reply(handshake_reply):
    return {"code": handshake_reply[0], "available": handshake_reply[1] == 1}

def get_cancel_command():
    return get_noarg_command(APICommandCode.CANCEL.value)

def get_has_data_command(port):
    return struct.pack("B3xI", APICommandCode.HAS_DATA.value, port)

def decode_has_data_command(has_data_cmd):
    return {"code": has_data_cmd[0], "port": int.from_bytes(has_data_cmd, "little")}


# Dictionary mapping API commands to their corresponding decoders
type_to_decoder = {
    APICommandCode.QUIT.value: decode_noarg_command,
    APICommandCode.CREATE_SOCK.value: decode_sock_command,
    APICommandCode.CLOSE_SOCK.value: decode_sock_command,
    APICommandCode.RECV.value: decode_recv_command,
    APICommandCode.SEND.value: decode_send_command,
    APICommandCode.JOIN.value: decode_lu_command,
    APICommandCode.LEAVE.value: decode_lu_command,
    APICommandCode.IS_ROUTER.value: decode_noarg_command,
    APICommandCode.ID.value: decode_noarg_command,
    APICommandCode.FLOOD.value: decode_flood_command,
    APICommandCode.REPLACE.value: decode_lu_command,
    APICommandCode.GET.value: decode_get_command,
    APICommandCode.START_IOT_DEVICE.value: decode_start_iot_device_command,
    APICommandCode.GET_VALUE.value: decode_get_value_command,
    APICommandCode.HANDSHAKE.value: decode_noarg_command,
    APICommandCode.HANDSHAKE_REPLY.value: decode_handshake_reply,
    APICommandCode.CANCEL.value: decode_noarg_command,
    APICommandCode.HAS_DATA.value: decode_has_data_command
}
