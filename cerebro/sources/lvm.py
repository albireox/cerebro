#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: José Sánchez-Gallego (gallegoj@uw.edu)
# @Date: 2021-03-27
# @Filename: lvm.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations

import asyncio
import re
from datetime import datetime

from typing import Optional

from cerebro import log

from .source import TCPSource


__all__ = ["GoveeSource", "Sens4Source"]


class GoveeSource(TCPSource):
    """Retrieves temperature and RH from a TCP server connected to a Govee BT device."""

    source_type = "govee"
    delay = 10

    def __init__(
        self,
        *args,
        address: str,
        device: Optional[str] = None,
        **kwargs,
    ):

        super().__init__(*args, **kwargs)

        assert device or address, "One of device or address are needed."

        self.device = device
        self.address = address.upper()

        self.bucket = self.bucket or "sensors"

    async def _read_internal(self) -> list[dict] | None:

        self.writer.write((f"status {self.address}\n").encode())
        await self.writer.drain()

        data = await asyncio.wait_for(self.reader.readline(), timeout=5)

        # Not found
        if data == b"?\n":
            return

        address, temp, hum, _, isot = data.decode().strip().split()

        date = datetime.fromisoformat(isot)
        temp = float(temp)
        hum = float(hum)

        # Check the timestamp. If the data point is too old, skip.
        if (datetime.utcnow() - date).seconds > 2 * self.delay:
            return None

        tags = self.tags.copy()
        tags["address"] = address.upper()
        tags["device"] = self.device

        if address != self.address:
            log.warning(
                f"{self.name}: mismatch between expected address "
                f"{self.address} and received {address}."
            )
            return None

        temp_point = {
            "measurement": "temperature",
            "fields": {"value": temp},
            "tags": tags,
            "time": date,
        }

        humid_point = {
            "measurement": "humidity",
            "fields": {"value": hum},
            "tags": tags,
            "time": date,
        }

        return [temp_point, humid_point]


class Sens4Source(TCPSource):
    """Reads pressure and temperature from multiple Sens4 transducers.

    The Sens4 provides this information over a serial interface but we assume there is
    a bidirectional byte stream between the serial device and a TCP socket.

    """

    source_type = "sens4"

    def __init__(
        self,
        *args,
        device_id: int,
        ccd: str = "NA",
        delay: float = 1,
        **kwargs,
    ):

        super().__init__(*args, **kwargs)

        self.device_id = device_id
        self.ccd = ccd

        self.delay = delay

        self.bucket = self.bucket or "sensors"

    async def _read_internal(self) -> list[dict] | None:

        self.writer.write((f"@{self.device_id:d}Q?\\").encode())
        await self.writer.drain()

        data = await asyncio.wait_for(self.reader.readuntil(b"\\"), timeout=5)
        data = data.decode()

        m = re.match(
            r"^@[0-9]{1,3}ACKQ"
            r"([0-9]+?.[0-9]+E[+-][0-9]+),"
            r"([0-9]+?.[0-9]+E[+-][0-9]+),"
            r"([0-9]+?.[0-9]+E[+-][0-9]+),"
            r"([0-9]+\.[0-9]+),.+\\$",
            data,
        )
        if not m:
            raise ValueError("Reply from device cannot be parsed.")

        pz, pir, cmb, temp = map(float, m.groups())

        tags = self.tags.copy()
        tags["ccd"] = self.ccd

        point = {
            "measurement": "pressure",
            "fields": {"pz": pz, "pir": pir, "cmb": cmb, "temp": temp},
            "tags": tags,
        }

        return [point]
