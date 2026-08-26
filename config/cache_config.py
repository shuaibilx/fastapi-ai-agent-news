import json

import redis.asyncio as redis

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

# 创建Redis连接
redis_client = redis.Redis(
    host=REDIS_HOST,  # Redis服务器的主机地址
    port=REDIS_PORT,  # Redis端口号
    db=REDIS_DB,  # Redis数据库编号，0-15
    decode_responses=True  # 是否将字节数据解码为字符串
)


# 设置 和 读取 （字符串 和 字典或列表） "[{}]"

# 【字符串】 本身就是  Redis 的原生数据类型，存取无需转换
# Python str  ──→  直接存入 Redis  ──→  取出就是 str  ✅ 无需转换
#
# 【列表/字典】 是 Python 内存对象，
# 存进Redis ： 序列化json.dumps()  Python对象 -> 字符串
# 取出Redis ： 反序列化json.loads() 字符串 -> Python对象
# Python dict ──→  ❌ 无法直接存入 Redis（不是字符串）
#                 ↓
#            json.dumps(dict) → JSON字符串 ──→ 存入 Redis
#                 ↓
#            取出 JSON字符串 ──→ json.loads() → 还原为 dict ✅

# 1. 读取：字符串
async def get_cache(key: str):
    try:
        return await redis_client.get(key)
    except Exception as e:
        print(f"获取缓存失败：{e}")
        return None


# 2. 读取：列表或字典
async def get_json_cache(key: str):
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)  # 序列化
        return None
    except Exception as e:
        print(f"获取 JSON 缓存失败：{e}")
        return None


# 3. 设置缓存 setex(key, expire, value)
async def set_cache(key: str, value: str, expire: int = 3600):
    try:
        if isinstance(value, (dict, list)):
            # 如果是字典或列表：转字符串再存
            value = json.dumps(value, ensure_ascii=False)  # 中文正常保存
        await redis_client.setex(key, expire, value)
        return True
    except Exception as e:
        print(f"设置缓存失败：{e}")
        return False
