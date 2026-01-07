from fastapi import status


class DBManagerException(Exception):
    """Exception raised for errors in the database manager"""

    status = status.HTTP_400_BAD_REQUEST


class RedisConnectionError(DBManagerException):
    """Exception raised for errors in the redis connection"""

    status = status.HTTP_502_BAD_GATEWAY


class GoogleSheetsConnectionError(DBManagerException):
    """Exception raised for errors in the google sheets connection"""

    status = status.HTTP_502_BAD_GATEWAY
