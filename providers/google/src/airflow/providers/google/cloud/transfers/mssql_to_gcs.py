#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""MsSQL to GCS operator."""

from __future__ import annotations

import datetime
import decimal
from collections.abc import Sequence
from functools import cached_property
from typing import TYPE_CHECKING

from airflow.providers.google.cloud.transfers.sql_to_gcs import BaseSQLToGCSOperator
from airflow.providers.microsoft.mssql.hooks.mssql import MsSqlHook

if TYPE_CHECKING:
    from airflow.providers.openlineage.extractors import OperatorLineage


class MSSQLToGCSOperator(BaseSQLToGCSOperator):
    """
    Copy data from Microsoft SQL Server to Google Cloud Storage in JSON, CSV or Parquet format.

    :param bit_fields: Sequence of fields names of MSSQL "BIT" data type,
        to be interpreted in the schema as "BOOLEAN". "BIT" fields that won't
        be included in this sequence, will be interpreted as "INTEGER" by
        default.
    :param mssql_conn_id: Reference to a specific MSSQL hook.

    **Example**:
        The following operator will export data from the Customers table
        within the given MSSQL Database and then upload it to the
        'mssql-export' GCS bucket (along with a schema file). ::

            export_customers = MSSQLToGCSOperator(
                task_id="export_customers",
                sql="SELECT * FROM dbo.Customers;",
                bit_fields=["some_bit_field", "another_bit_field"],
                bucket="mssql-export",
                filename="data/customers/export.json",
                schema_filename="schemas/export.json",
                mssql_conn_id="mssql_default",
                gcp_conn_id="google_cloud_default",
                dag=dag,
            )

    .. seealso::
        For more information on how to use this operator, take a look at the guide:
        :ref:`howto/operator:MSSQLToGCSOperator`

    """

    ui_color = "#e0a98c"

    type_map = {2: "BOOLEAN", 3: "INTEGER", 4: "TIMESTAMP", 5: "NUMERIC"}

    def __init__(
        self,
        *,
        bit_fields: Sequence[str] | None = None,
        mssql_conn_id="mssql_default",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.mssql_conn_id = mssql_conn_id
        self.bit_fields = bit_fields or []

    @cached_property
    def db_hook(self) -> MsSqlHook:
        return MsSqlHook(mssql_conn_id=self.mssql_conn_id)

    def query(self):
        """
        Query MSSQL and returns a cursor of results.

        :return: mssql cursor
        """
        conn = self.db_hook.get_conn()
        cursor = conn.cursor()
        cursor.execute(self.sql)
        return cursor

    def field_to_bigquery(self, field) -> dict[str, str]:
        if field[0] in self.bit_fields:
            field = (field[0], 2)

        return {
            "name": field[0].replace(" ", "_"),
            "type": self.type_map.get(field[1], "STRING"),
            "mode": "NULLABLE",
        }

    @classmethod
    def convert_type(cls, value, schema_type, **kwargs):
        """
        Take a value from MSSQL and convert it to a value safe for JSON/Google Cloud Storage/BigQuery.

        Datetime, Date and Time are converted to ISO formatted strings.
        """
        if isinstance(value, decimal.Decimal):
            return float(value)
        if isinstance(value, datetime.date | datetime.time):
            return value.isoformat()
        return value

    def get_openlineage_facets_on_start(self) -> OperatorLineage | None:
        from airflow.providers.common.compat.openlineage.facet import SQLJobFacet
        from airflow.providers.common.compat.openlineage.utils.sql import get_openlineage_facets_with_sql
        from airflow.providers.openlineage.extractors import OperatorLineage

        sql_parsing_result = get_openlineage_facets_with_sql(
            hook=self.db_hook,
            sql=self.sql,
            conn_id=self.mssql_conn_id,
            database=None,
        )
        gcs_output_datasets = self._get_openlineage_output_datasets()
        if sql_parsing_result:
            sql_parsing_result.outputs = gcs_output_datasets
            return sql_parsing_result
        return OperatorLineage(outputs=gcs_output_datasets, job_facets={"sql": SQLJobFacet(self.sql)})
