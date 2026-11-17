import sys

from .dpi import enable_dpi_awareness


def voice() -> None:
    enable_dpi_awareness()
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "daemon":
        from .daemon import main
        main(sys.argv[2:])
    elif command == "service":
        from .service import main
        main(sys.argv[2:])
    else:
        from .main import main
        main()


def mcp() -> None:
    enable_dpi_awareness()
    from .mcp_server import main
    main()
