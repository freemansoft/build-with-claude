---
type: llm
focus: trace
weight: 1
---

The answer identifies that Desktop sends the owner's name in a "name" field while buddy_protocol.py reads msg["owner"], so the name is dropped.
