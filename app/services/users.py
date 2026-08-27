import uuid
from datetime import timedelta, datetime
from multiprocessing.managers import rebuild_as_list

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.models.users import User, UserToken
from app.schemas.users import UserRequest, UserUpdateRequest, UserChangePasswordRequest
from app.core import security


# 判断是否存在相同用户名 ： 根据用户名查询数据库
async def get_user_by_username(db: AsyncSession, username: str):
    query = select(User).where(User.username == username)  # 构造待执行的 sql 语句
    result = await db.execute(query)  # 执行sql语句，返回一个通用结果容器
    return result.scalar_one_or_none()  # 从容器中 提取 单个ORM实例


# 创建用户
async def create_user(db: AsyncSession, user_data: UserRequest):
    # 先加密处理
    hashed_password = security.get_hash_password(user_data.password)
    user = User(username=user_data.username, password=hashed_password)
    db.add(user)
    await db.commit()
    await db.refresh(user)  # 从数据库读回最新的user
    return user


# 生成token ： 在后续请求中证明自己已经登录过
async def create_token(db: AsyncSession, user_id: int):
    # 生成token  +  设置过期时间  +  查询数据库当前用户是否有token  +  有：更新；没有：添加
    token = str(uuid.uuid4())

    expire_at = datetime.now() + timedelta(days=7)
    query = select(UserToken).where(UserToken.user_id == user_id)
    result = await db.execute(query)
    user_token = result.scalar_one_or_none()
    if user_token:
        user_token.token = token
        user_token.expires_at = expire_at
        await db.commit()
    else:
        user_token = UserToken(user_id=user_id, token=token, expires_at=expire_at)
        db.add(user_token)
        await db.commit()

    return token


# 验证用户
async def authenticate_user(db: AsyncSession, username: str, password: str):
    user = await get_user_by_username(db, username)
    if not user:
        return None
    if not security.verify_password(password, user.password):
        return None

    return user


# 根据token 查询用户 ： 验证 Token -》 查询用户
async def get_user_by_token(db: AsyncSession, token: str):
    # 通过token，判断用户是否存在以及token是否过期
    query = select(UserToken).where(UserToken.token == token)
    result = await db.execute(query)
    usertoken = result.scalar_one_or_none()
    if not usertoken or usertoken.expires_at < datetime.now():
        return None
    # 通过
    query = select(User).where(User.id == usertoken.user_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    return user


# 更新用户信息：update更新 -》 检查是否命中 -》 获取更新后的用户信息返回
async def update_user(db: AsyncSession, user_data: UserUpdateRequest, username: str):
    # update(User).where(User.username == username).values(字段=值,字段=值)
    # user_data 是一个Pydantic类型 -》 dict类型 ： user_data.model_dump()
    # dict 类型 -》 关键字参数 ， ** 解包
    # 没有设置的值不更新
    query = update(User).where(User.username == username).values(**user_data.model_dump(
        exclude_none=True,
        exclude_unset=True
    ))
    result = await db.execute(query)
    await db.commit()

    # 检查更新
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user_update = await get_user_by_username(db, username)
    return user_update


# 修改用户密码： 验证旧密码 -》 新密码加密 -》 修改密码
async def change_password(db: AsyncSession, user: User, password_data: UserChangePasswordRequest):
    if not security.verify_password(password_data.old_password, user.password):
        return False
    hashed_password = security.get_hash_password(password_data.new_password)
    user.password = hashed_password
    # 更新：由SQLAlchemy 正在接管这个 User 对象，确保可以 commit
    # 规避 session 过期或关闭导致的不能提交的问题
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return True
