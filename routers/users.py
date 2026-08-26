from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from crud import users
from crud.users import change_password
from models.users import User
from schemas.users import UserRequest, UserInfoResponse, UserAuthResponse, UserUpdateRequest, UserChangePasswordRequest
from utils.auth import get_current_user
from utils.response import success_response

router = APIRouter(prefix="/api/user", tags=["users"])


# 用户注册
@router.post("/register")
async def register(user_data: UserRequest, db: AsyncSession = Depends(get_db)):
    # 注册逻辑 ： 验证用户是否存在 -》 创建用户 -》 生成token -》 响应结果
    existing_user = await users.get_user_by_username(db, user_data.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="用户已存在")
    user = await users.create_user(db, user_data)
    token = await users.create_token(db, user.id)

    # return {
    #     "code": 200,
    #     "message": "注册成功",
    #     "data": {
    #         "token": token,
    #         "userInfo": {
    #             "id": user.id,
    #             "username": user_data.username,
    #             "bio": user.bio,
    #             "avatar": user.avatar,
    #         }
    #     }
    # }
    response_data = UserAuthResponse(token=token, userInfo=UserInfoResponse.model_validate(
        user))  # UserInfoResponse必须配置model_config = ConfigDict(from_attributes=True)
    # serInfoResponse.model_validate作用： 字段白名单过滤 + 结构转换 -》  user实例 ->  UserInfoResponse实例
    return success_response(message="注册成功", data=response_data)


# 用户登录
@router.post("/login")
async def login(user_data: UserRequest, db: AsyncSession = Depends(get_db)):
    # 登录业务 ： 进入请求 -》 检查用户是否存在 ——》存在：验证密码 -》 密码一直：生成访问令牌 -》 响应结果
    user = await users.authenticate_user(db, user_data.username, user_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    token = await users.create_token(db, user.id)
    response_data = UserAuthResponse(token=token, userInfo=UserInfoResponse.model_validate(user))
    return success_response("登录成功", data=response_data)


# 获取用户信息 ： 查Token查用户 -》 封装crud ——》 功能整合成一个工具函数 -》路由导入使用
@router.get("/info")
async def get_user_info(user: User = Depends(get_current_user)):  # 依赖可以继续依赖其他依赖。
    #       get_user_info
    #       ↓ Depends
    #   get_current_user
    #   ├── authorization ← Header
    #   └── db            ← Depends(get_db)
    #                                  ↓
    #                                get_db
    return success_response(message="获取用户信息成功", data=UserInfoResponse.model_validate(user))


# 修改用户信息：
# 参数：用户输入的 + 验证Token的 + db（调用更新的方法）
@router.put("/update")
async def update_user_info(user_data: UserUpdateRequest, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    user = await users.update_user(db, user_data, user.username)
    return success_response(message="更新用户信息成功", data=UserInfoResponse.model_validate(user))


# 修改用户密码
@router.put("/password")
async def update_password(password_data: UserChangePasswordRequest,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    res = await change_password(db, user, password_data)
    if not res:
        raise HTTPException(status_code=500, detail="旧密码验证失败")
    return success_response(message="修改密码成功")
