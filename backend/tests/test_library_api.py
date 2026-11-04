"""HTTP integration tests for the textbook page-management workflow."""

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from ruangao_note.core.config import get_settings
from ruangao_note.db.base import Base
from ruangao_note.db.session import create_database_engine, get_db
from ruangao_note.main import app


def png_bytes(color: tuple[int, int, int]) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (24, 18), color=color).save(stream, format="PNG")
    return stream.getvalue()


def test_complete_book_chapter_and_page_api_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    engine = create_database_engine(f"sqlite:///{tmp_path / 'api-test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            book_response = client.post(
                "/api/books",
                json={"title": "软件设计师教程", "edition": "第 5 版"},
            )
            assert book_response.status_code == 201
            book_id = book_response.json()["id"]

            chapter_response = client.post(
                f"/api/books/{book_id}/chapters",
                json={"chapter_number": 1, "title": "计算机系统基础"},
            )
            assert chapter_response.status_code == 201
            chapter_id = chapter_response.json()["id"]
            chapter_list = client.get(f"/api/books/{book_id}/chapters")
            assert chapter_list.status_code == 200
            assert chapter_list.json()[0]["id"] == chapter_id

            files = [
                ("files", (f"page-{index + 1:02}.png", png_bytes((index, index + 1, index + 2)), "image/png"))
                for index in range(24)
            ]
            upload_response = client.post(
                f"/api/chapters/{chapter_id}/pages",
                files=files,
            )
            assert upload_response.status_code == 201
            uploaded = upload_response.json()["pages"]
            assert len(uploaded) == 24
            assert [page["sort_order"] for page in uploaded] == list(range(24))

            page_id = uploaded[0]["id"]
            reorder_response = client.put(
                f"/api/chapters/{chapter_id}/pages/order",
                json={"page_ids": [page["id"] for page in reversed(uploaded)]},
            )
            assert reorder_response.status_code == 200
            assert reorder_response.json()[0]["id"] == uploaded[-1]["id"]
            reorder_back = client.put(
                f"/api/chapters/{chapter_id}/pages/order",
                json={"page_ids": [page["id"] for page in uploaded]},
            )
            assert reorder_back.status_code == 200

            preview = client.get(
                f"/api/chapters/{chapter_id}/pages/{page_id}/image"
            )
            assert preview.status_code == 200
            assert preview.content == png_bytes((0, 1, 2))

            number_response = client.patch(
                f"/api/chapters/{chapter_id}/pages/{page_id}/number",
                json={"textbook_page_number": 101},
            )
            assert number_response.status_code == 200
            assert number_response.json()["textbook_page_number"] == 101

            rotation_response = client.patch(
                f"/api/chapters/{chapter_id}/pages/{page_id}/rotation",
                json={"rotation": 90},
            )
            assert rotation_response.status_code == 200
            assert rotation_response.json()["rotation"] == 90

            duplicate_response = client.post(
                f"/api/chapters/{chapter_id}/pages",
                files=[("files", ("duplicate.png", png_bytes((0, 1, 2)), "image/png"))],
            )
            assert duplicate_response.status_code == 201
            assert duplicate_response.json()["pages"] == []
            assert len(duplicate_response.json()["duplicates"]) == 1

            replacement_response = client.put(
                f"/api/chapters/{chapter_id}/pages/{page_id}/replace",
                files={"file": ("replacement.png", png_bytes((100, 101, 102)), "image/png")},
            )
            assert replacement_response.status_code == 200
            replacement = replacement_response.json()
            assert replacement["replaces_page_id"] == page_id
            assert replacement["sort_order"] == 0
            historical_preview = client.get(
                f"/api/chapters/{chapter_id}/pages/{page_id}/image"
            )
            assert historical_preview.status_code == 200
            assert historical_preview.content == png_bytes((0, 1, 2))

            current_pages = client.get(f"/api/chapters/{chapter_id}/pages").json()
            assert len(current_pages) == 24
            assert current_pages[0]["id"] == replacement["id"]

            delete_response = client.delete(
                f"/api/chapters/{chapter_id}/pages/{replacement['id']}"
            )
            assert delete_response.status_code == 204
            current_pages = client.get(f"/api/chapters/{chapter_id}/pages").json()
            assert len(current_pages) == 23
            assert [page["sort_order"] for page in current_pages] == list(range(23))
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        engine.dispose()
