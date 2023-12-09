# A new connection is spinned up on every import, so do with this as you will, you can have a single global one, or spin up a connection per-file.

import redis

RDB = redis.Redis(
    host='127.0.0.1',
    port=6379,
    decode_responses=True)