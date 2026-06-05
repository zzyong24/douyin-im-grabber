import contextlib
import io
import json
import unittest

from douyin_im_grabber import net_grab


def varint(value):
    out = []
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            b |= 0x80
        out.append(b)
        if not value:
            return bytes(out)


def field_varint(fn, value):
    return varint((fn << 3) | 0) + varint(value)


def field_bytes(fn, value):
    return varint((fn << 3) | 2) + varint(len(value)) + value


class NetGrabTests(unittest.TestCase):
    def test_parse_args_accepts_help_without_starting_grab(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                net_grab.parse_args(["--help"])

        self.assertEqual(cm.exception.code, 0)

    def test_parse_proto_body_decodes_minimal_get_user_message_response(self):
        msg = b"".join(
            [
                field_bytes(1, b"7566658350746845732"),
                field_varint(3, 7647741162309012005),
                field_varint(5, 1234567890123456789),
                field_varint(7, 1780628501936000),
                field_varint(10, 1780628501936),
                field_bytes(8, "hello".encode("utf-8")),
                field_bytes(14, b"MS4wLjABAAAA"),
            ]
        )
        msg_container = field_bytes(1, msg)
        f2048 = field_bytes(2, msg_container)
        envelope = field_bytes(2048, f2048)
        response = field_bytes(6, envelope)

        messages = net_grab.parse_proto_body(response)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["conv_id"], "7566658350746845732")
        self.assertEqual(messages[0]["server_id"], "7647741162309012005")
        self.assertEqual(messages[0]["text"], "hello")

    def test_parse_messages_from_response_decodes_get_by_conversation(self):
        msg = b"".join(
            [
                field_bytes(1, b"7566658350746845732"),
                field_varint(3, 7647741162309012005),
                field_varint(4, 1780628501936000),
                field_varint(6, 7),
                field_varint(7, 1234567890123456789),
                field_bytes(8, "older hello".encode("utf-8")),
                field_bytes(
                    9,
                    field_bytes(1, b"s:server_message_create_time")
                    + field_bytes(2, b"1780626355540"),
                ),
            ]
        )
        f301 = field_bytes(1, msg) + field_varint(3, 0)
        response = field_bytes(6, field_bytes(301, f301))

        messages = net_grab.parse_messages_from_response(
            "https://imapi.douyin.com/v1/message/get_by_conversation",
            response,
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["server_id"], "7647741162309012005")
        self.assertEqual(messages[0]["type_code"], 7)
        self.assertEqual(messages[0]["text"], "older hello")
        self.assertEqual(messages[0]["created_at_ms"], 1780626355540)

    def test_display_text_keeps_markdown_non_text_messages_compact(self):
        image_message = {
            "type_code": 27,
            "text": json.dumps({"aweType": 2702, "resource_url": {"origin_url_list": ["https://example.com/a.jpg"]}}),
        }

        self.assertFalse(net_grab.is_text_message(image_message))
        self.assertEqual(net_grab.display_text(image_message), "[图片]")

    def test_display_text_extracts_actual_text_payload(self):
        text_message = {
            "type_code": 7,
            "text": json.dumps({"text": "hello from json", "aweType": 700}),
        }

        self.assertTrue(net_grab.is_text_message(text_message))
        self.assertEqual(net_grab.display_text(text_message), "hello from json")


if __name__ == "__main__":
    unittest.main()
