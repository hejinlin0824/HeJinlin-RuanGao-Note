# TP-03 本地验收说明：教材图片导入与页面管理

## 1. 更新环境

拉取 `dev` 后安装新增依赖（Pillow、python-multipart）：

```powershell
git pull origin dev
python -m pip install -e ".[dev]"
.\test.bat
```

先确认一键测试全部通过，再启动服务：

```powershell
uvicorn ruangao_note.main:app --app-dir backend --reload --host 127.0.0.1 --port 8765
```

打开 http://127.0.0.1:8765/docs 。

## 2. 端到端验收

1. 调用 `POST /api/books` 创建教材，例如：
   `{"title":"软件设计师教程","edition":"第 5 版"}`。
2. 复制返回的 `id`，调用 `POST /api/books/{book_id}/chapters` 创建第 1 章。
3. 在 `POST /api/chapters/{chapter_id}/pages` 选择 20–24 张图片上传。允许 JPEG、PNG、WEBP、TIFF；单张默认不超过 20 MiB，每批最多 30 张、总计不超过 300 MiB。
4. 检查返回结果：`sort_order` 从 0 连续递增；`sha256` 为 64 位；MIME、文件大小、宽高正确。
5. 再上传其中一张相同图片：应返回 `duplicates` 提示，不应新增页面。
6. 调用 `PUT /api/chapters/{chapter_id}/pages/order`，传入全部页面 ID 的新顺序；再次 GET，确认顺序已持久化。
7. 调用页码更新和旋转接口，确认教材页码与旋转角度更新。旋转只改变显示元数据，不修改原始图片字节。
8. 调用预览接口，确认返回图片可正常打开。
9. 替换一张页面：新记录的 `replaces_page_id` 指向旧页面；旧页面状态归档，旧文件仍存在。
10. 删除一张页面：页面从活动列表消失，但原始文件与归档记录保留。
11. 重启服务，再次查询页面并预览图片，确认文件与数据库元数据仍可读取。

## 3. 安全与边界检查

- 将非图片文件伪装成 `.png` 上传，应返回 415。
- 上传空文件、超大图片或超出像素限制的图片，应拒绝。
- 传入不完整、重复或不存在的页面 ID 顺序，应返回 422。
- 访问其他章节的页面 ID，应返回 404。
- 原始文件名不会作为磁盘路径；磁盘路径由系统生成。
- 图片文件保存在 `STORAGE_DIR`（默认 `./data/uploads`），数据库仅保存相对路径。
- 删除和替换均采用归档/新记录方式，不物理覆盖原图。

## 4. 当前实现边界

TP-03 当前实现本地文件系统存储，不包含对象存储、图片裁切、EXIF 自动旋转和 OCR。旋转接口只记录 0/90/180/270 度的展示元数据；后续前端预览应按该字段旋转显示。OCR 与图像预处理属于 TP-04。
