from .dpi import enable_dpi_awareness


def voice() -> None:
    enable_dpi_awareness()
    from .main import main
    main()


def mcp() -> None:
    enable_dpi_awareness()
    from .mcp_server import main
    main()
