import pandas as pd
from googleapiclient.discovery import Resource
from app.config import google_sheets_settings
from app.core.exceptions import GoogleSheetsConnectionError


class SheetsService:
    """This is a class to handle the sheets actual service here are all the implementation details rather than showing them in the router"""

    def __init__(self, service: Resource):
        self.service = service
        self.range_used = "A1:K1000"

    async def get_data_in_dataframe(self) -> pd.DataFrame:
        rows = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=google_sheets_settings.GOOGLE_SHEETS_SPREADSHEET_ID,
                range=self.range_used,
            )
            .execute()
            .get("values", [])
        )

        if len(rows) == 0:
            raise GoogleSheetsConnectionError("No data found in the sheet")

        return pd.DataFrame(rows[1:], columns=rows[0])

    def clean_row_for_sheets(self, row):
        """Convert None and 'None' strings to empty strings for Google Sheets."""
        return ["" if (v is None or str(v) == "None") else str(v) for v in row]

    async def _write_new_data(self, data: pd.DataFrame):
        data_on_sheet = await self.get_data_in_dataframe()
        sheet_phone_numbers = data_on_sheet["TELEFONO"].unique()
        db_phone_numbers = data["TELEFONO"].unique()

        for phone_number in db_phone_numbers:
            if phone_number not in sheet_phone_numbers:
                row_to_add = data[data["TELEFONO"] == phone_number].iloc[0].tolist()

                insert_request = {
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": 0,  # First sheet (tab) in the spreadsheet
                                    "dimension": "ROWS",
                                    "startIndex": 1,  # After row 1 (0-indexed, so 1 = row 2)
                                    "endIndex": 2,
                                },
                                "inheritFromBefore": False,
                            }
                        }
                    ]
                }
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=google_sheets_settings.GOOGLE_SHEETS_SPREADSHEET_ID,
                    body=insert_request,
                ).execute()

                response = (
                    self.service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=google_sheets_settings.GOOGLE_SHEETS_SPREADSHEET_ID,
                        range="A2:K2",
                        valueInputOption="RAW",
                        body={"values": [self.clean_row_for_sheets(row_to_add)]},
                    )
                    .execute()
                )

                if response.get("updatedCells") > 0:
                    data_on_sheet = await self.get_data_in_dataframe()
                    sheet_phone_numbers = data_on_sheet["TELEFONO"].unique()

    def _create_update_request(
        self, row_to_update: list, db_row: list, row_index_on_sheet: int
    ):
        dicts_rows = []
        for i, (value_to_update, value_on_sheet) in enumerate(
            zip(row_to_update, db_row)
        ):
            if (
                value_to_update != value_on_sheet
                and value_on_sheet.lower() == value_on_sheet
            ):
                dicts_rows.append(
                    {
                        "range": f"{chr(65 + i)}{row_index_on_sheet + 2}",
                        "values": [[value_to_update]],
                    }
                )
        return dicts_rows

    async def _update_bot_data(self, data: pd.DataFrame):
        data_on_sheet = await self.get_data_in_dataframe()
        sheet_phone_numbers = data_on_sheet["TELEFONO"].unique()
        db_phone_numbers = data["TELEFONO"].unique()

        all_updates = []

        for phone_number in db_phone_numbers:
            if phone_number in sheet_phone_numbers:
                row_to_update = data[data["TELEFONO"] == phone_number].iloc[0]
                db_row = data_on_sheet[data_on_sheet["TELEFONO"] == phone_number].iloc[
                    0
                ]
                row_index_on_sheet = data_on_sheet[
                    data_on_sheet["TELEFONO"] == phone_number
                ].index[0]

                # Check if any value is different
                if any(row_to_update != db_row):
                    # Get the list of ValueRange objects for this row
                    row_updates = self._create_update_request(
                        row_to_update, db_row, row_index_on_sheet
                    )
                    all_updates.extend(row_updates)

        if all_updates:
            update_request = {
                "valueInputOption": "RAW",
                "data": all_updates,
            }
            self.service.spreadsheets().values().batchUpdate(
                spreadsheetId=google_sheets_settings.GOOGLE_SHEETS_SPREADSHEET_ID,
                body=update_request,
            ).execute()

    async def update_sheet(self, data: pd.DataFrame):
        """Updating the data on the google sheet"""
        await self._write_new_data(data)
        await self._update_bot_data(data)
