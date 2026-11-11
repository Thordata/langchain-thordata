"""Fetch company records using THORDATA_API_KEY or THORDATA_API_TOKEN."""

import argparse
import json

from langchain_thordata import ThorDataClient, ThorDataWebScraperError


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a LinkedIn company profile.")
    parser.add_argument("url", help="LinkedIn company URL")
    args = parser.parse_args()
    try:
        with ThorDataClient() as client:
            response = client.scrape_response(
                "linkedin_company_information_by-url",
                {"url": args.url},
                max_wait_seconds=300,
                include_errors=True,
            )
        print(
            json.dumps(
                {
                    "task_id": response.task_id,
                    "status": response.status,
                    "record_count": response.record_count,
                    "error_record_count": response.error_record_count,
                    "result": response.result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except ThorDataWebScraperError as error:
        print(
            json.dumps(
                {
                    "error_code": error.error_code,
                    "service_code": error.service_code,
                    "task_id": error.task_id,
                    "stage": error.stage,
                    "message": str(error),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
