# coding: utf-8

import json
import io
import os
import time

from ros_llm_voice_agent.compat import to_text


class JsonlMemoryStore:
    def __init__(self, path="/tmp/llm_voice_agent/memory.jsonl"):
        self.path = path
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)

    def remember(self, key, value, reason=""):
        record = {
            "ts": time.time(),
            "key": to_text(key),
            "value": to_text(value),
            "reason": to_text(reason),
        }
        with io.open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def recall(self, query="", limit=5):
        if not os.path.exists(self.path):
            return []
        query = to_text(query).lower()
        records = []
        with io.open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not query or query in json.dumps(record, ensure_ascii=False).lower():
                    records.append(record)
        return records[-int(limit) :]
