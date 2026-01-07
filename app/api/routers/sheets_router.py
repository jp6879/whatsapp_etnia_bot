import pandas as pd
from typing import List, Dict, Any
from fastapi import APIRouter
from ..dependencies import SheetsServiceDep
from ..tag import APITag

router = APIRouter(prefix="/sheets", tags=[APITag.SHEETS])


@router.get("/data")
async def get_data_from_google_sheets(service: SheetsServiceDep):
    """Getting all the data from the google sheet"""
    return await service.get_data_in_dataframe()


@router.post("/update")
async def update_data_on_google_sheets(
    data: List[Dict[str, Any]], service: SheetsServiceDep
):
    """Updating the data on the google sheet"""
    data = pd.DataFrame(data)
    return await service.update_sheet(data)
