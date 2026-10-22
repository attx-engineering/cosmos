# Copyright 2026 ATTX, Inc.
# All Rights Reserved.
#
# This program is free software; you can modify and/or redistribute it
# under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation; version 3 with
# attribution addendums as found in the LICENSE.txt
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from openc3.script.cosmos_calendar import create_timeline_activity


class TestCreateTimelineActivity(unittest.TestCase):
    def setUp(self):
        self.response = Mock()
        self.response.status_code = 201
        self.response.text = '{"kind": "command"}'
        self.start = datetime.now(timezone.utc) + timedelta(hours=1)
        self.stop = self.start + timedelta(minutes=1)

    @patch("openc3.script.API_SERVER")
    def test_asks_the_server_to_approve_a_hazardous_command_when_told_to(self, api_server):
        api_server.request.return_value = self.response
        create_timeline_activity(
            "TL", "COMMAND", self.start, self.stop, data={"command": "INST VENT"}, approve_hazardous=True
        )
        args, kwargs = api_server.request.call_args
        self.assertEqual(args, ("post", "/openc3-api/timeline/TL/activities"))
        self.assertIs(kwargs["data"]["approve_hazardous"], True)
        self.assertEqual(kwargs["data"]["data"], {"command": "INST VENT"})

    @patch("openc3.script.API_SERVER")
    def test_never_asks_for_an_approval_unless_told_to(self, api_server):
        api_server.request.return_value = self.response
        create_timeline_activity("TL", "COMMAND", self.start, self.stop, data={"command": "INST VENT"})
        self.assertNotIn("approve_hazardous", api_server.request.call_args[1]["data"])

    @patch("openc3.script.API_SERVER")
    def test_refuses_approve_hazardous_on_an_activity_that_is_not_a_command(self, api_server):
        with self.assertRaisesRegex(RuntimeError, "approve_hazardous is only for a command activity"):
            create_timeline_activity(
                "TL", "SCRIPT", self.start, self.stop, data={"script": "INST/vent.py"}, approve_hazardous=True
            )
        api_server.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
