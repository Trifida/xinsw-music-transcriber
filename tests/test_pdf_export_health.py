def test_health_reports_server_pdf_export_capability():
    """PDF 排版状态属于服务器能力；LilyPond 缺失不能让健康检查失败。"""
    from musicmaster.web.server import health

    result = health()
    assert result["ok"] is True
    assert "pdf_export" in result
    assert isinstance(result["pdf_export"]["ready"], bool)
    assert isinstance(result["pdf_export"]["source_fallback"], bool)
    if result["pdf_export"]["ready"]:
        assert result["pdf_export"]["engine"] == "LilyPond"
    else:
        assert result["pdf_export"]["engine"] is None
