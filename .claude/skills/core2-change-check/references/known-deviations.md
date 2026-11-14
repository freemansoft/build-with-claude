# Known deviations from REFERENCE.md

Where the Core2 bundle (and the shared `buddy/device/` modules) differ
from [REFERENCE.md](https://github.com/anthropics/claude-desktop-buddy/blob/main/REFERENCE.md).
Keep this list current: add a deviation when one is found or chosen,
and remove it when it's fixed.

## Intended

| Area                          | Reference                   | This repo                                                                           | Why                                                                                               |
| ----------------------------- | --------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `stats.vel`                   | median seconds to approve   | always 0 on the Core2                                                               | velocity isn't supported yet; 0 makes Desktop show `--s`                                          |
| `stats.nap`                   | nap seconds                 | count of idle periods                                                               | feeds planned pet features                                                                        |
| `stats.lvl`                   | level from tokens           | level from approvals                                                                | feeds planned pet features                                                                        |
| `sec`                         | `true` once bonded          | always `false`                                                                      | UIFlow 2.0's BLE build has no pairing API, so the link is unauthenticated                         |
| `unpair`                      | erase bonds, ack `ok:true`  | acks `{"ok":false,"pending":true,...}`, waits up to 30 s for on-device confirmation | anyone in range can write to an unauthenticated link                                              |
| Folder push                   | ack each step               | `char_begin` / `file` / `chunk` / `file_end` / `char_end` answered `ok:false`       | refusing file writes on an unauthenticated link (see `buddy/references/protocol.md`)              |
| Status reply (Cardputer only) | `{"ack","ok","data":{...}}` | flat fields, no `ok` / `data`                                                       | the Core2 wraps it in `_Protocol`; Cardputer fix pending hardware testing (see `buddy/README.md`) |

## Not yet decided or fixed

| Area                 | Reference                                      | This repo                                                      |
| -------------------- | ---------------------------------------------- | -------------------------------------------------------------- |
| Error key in acks    | `error`                                        | `err`                                                          |
| Refusing folder push | don't ack `char_begin` (Desktop times out)     | sends `ok:false` acks                                          |
| Dead link            | no heartbeat for ~30 s → treat as disconnected | no heartbeat timeout found; relies on the BLE disconnect event |
| `time`               | `{"time":[epoch, tz_offset]}`                  | recognized and ignored                                         |
