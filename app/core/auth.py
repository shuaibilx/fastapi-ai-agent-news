from fastapi import HTTPException
from fastapi.params import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.core.database import get_db
from app.services import users


# # 从请求头中取出 JWT Token ，验证后返回当前登录用户对象
# async def get_current_user(authorization: str = Header(..., alias="Authorization"), db: AsyncSession = Depends(
#     get_db)):
#     # authorization: str = Header(..., alias="Authorization") ： 依赖注入的写法，从HTTP请求头中取出 Authorization 这个字段的值
#     # 之所以要alias，因为Python变量名不能以大写字母开头，而HTTP请求头的标准字段名是 Authorization （首字母大写）
#     # Token 在请求中的位置 ：请求头
#     # 请求头示例：
#     # GET / api / user / profile HTTP / 1.1
#     # Host: localhost:8000
#     # Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxfQ.xxx
#
#     # token = authorization.split(" ")[1]  # 以空格分隔authorization成列表，取第二个元素
#     token = authorization.replace("Bearer ", "")
#     user = await users.get_user_by_token(db, token)
#     if not user:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的令牌或已过期的令牌")
#     return user

async def get_current_user(
        authorization: str | None = Header(default=None, alias="Authorization"),
        db: AsyncSession = Depends(get_db),
):
    # ① 统一转小写判断前缀（兼容 Bearer / bearer / BEARER）
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 头格式错误，应为: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ② 只去掉开头的 "Bearer "（7个字符），不影响 token 内容
    token = authorization[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 不能为空",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ③ 查用户
    user = await users.get_user_by_token(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌或已过期的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
