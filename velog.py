import os
import re
import sys
import yaml
import requests
from dotenv import load_dotenv

load_dotenv()

GRAPHQL_URL = "https://v3.velog.io/graphql"
ACCESS_TOKEN = os.getenv("VELOG_ACCESS_TOKEN")


def _gql(query: str, variables: dict) -> dict:
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables},
        cookies={"access_token": ACCESS_TOKEN},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def _make_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug


def parse_md(filepath: str) -> tuple[dict, str]:
    """마크다운 파일에서 frontmatter와 본문을 분리해 반환"""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        raise ValueError("frontmatter가 없습니다. 파일 상단에 --- 로 시작하는 메타정보를 추가하세요.")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("frontmatter 형식이 올바르지 않습니다. --- 로 열고 닫아야 합니다.")

    meta = yaml.safe_load(parts[1])
    body = parts[2].strip()
    return meta, body


def upload_post(
    title: str,
    body: str,
    tags: list[str] = [],
    is_private: bool = False,
    is_temp: bool = False,
) -> dict:
    mutation = """
    mutation WritePost($input: WritePostInput!) {
      writePost(input: $input) {
        id
        title
        url_slug
        user { username }
      }
    }
    """
    variables = {
        "input": {
            "title": title,
            "body": body,
            "tags": tags,
            "is_markdown": True,
            "is_temp": is_temp,
            "is_private": is_private,
            "url_slug": _make_slug(title),
            "thumbnail": None,
            "meta": {},
            "series_id": None,
        }
    }
    result = _gql(mutation, variables)
    post = result["writePost"]
    username = post["user"]["username"]
    url = f"https://velog.io/@{username}/{post['url_slug']}"
    print(f"업로드 완료: {url}")
    return post


def main():
    if len(sys.argv) < 2:
        print("사용법: python3 velog.py <파일명.md>")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"파일을 찾을 수 없습니다: {filepath}")
        sys.exit(1)

    meta, body = parse_md(filepath)

    title = meta.get("title")
    if not title:
        raise ValueError("frontmatter에 title이 없습니다.")

    tags = meta.get("tags", [])
    is_private = meta.get("private", False)
    is_temp = meta.get("temp", False)

    upload_post(title=title, body=body, tags=tags, is_private=is_private, is_temp=is_temp)


if __name__ == "__main__":
    main()
