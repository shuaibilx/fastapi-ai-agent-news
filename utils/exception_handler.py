from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from utils.exception import http_exception_handler, general_exception_handler, sqlalchemy_error_handler, \
    integrity_error_handler


def register_exception_handlers(app):
    """
    注册全局异常处理：子类在前，父类在后；具体在前，抽象在后
    """
    app.add_exception_handler(HTTPException, http_exception_handler)  # 参数1 ： 异常类 ， 参数2 ： 异常处理函数名
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    app.add_exception_handler(Exception, general_exception_handler)

# 全局异常处理器 ： 异常发生之后，格式化异常的内容。 与 业务层 是分离的
# raise HTTPException 。 业务层，通过条件判断语句判断异常触发的时机，返回抛出的异常内容
