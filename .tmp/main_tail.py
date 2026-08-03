
    flag 分发优先级（自上而下短路）：

        ``--smoke`` > ``--once`` > ``--autonomous`` > ``--serve`` >
        ``--as-supervised`` > （默认）交互模式。

    Returns:
        对应子命令的退出码（cmd_smoke/cmd_once 可能 0 或 1，其余始终 0）。
    """
    parser = argparse.ArgumentParser(prog="xragent", description="XRAgent 息壤")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--once", type=str, default=None)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--as-supervised", action="store_true")
    parser.add_argument("--autonomous", action="store_true", help="自驱动循环")
    parser.add_argument("--interval", type=int, default=30, help="autonomous 每轮间隔秒")
    parser.add_argument("--max-rounds", type=int, default=0, help="autonomous 最大轮数（0=无限）")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()

    _apply_freeze(args.freeze)

    if args.smoke:
        return cmd_smoke()
    if args.once:
        return cmd_once(args.once, args.freeze)
    if args.autonomous:
        return cmd_autonomous(interval_s=args.interval, max_rounds=args.max_rounds)
    if args.serve:
        return cmd_serve(args.freeze)
    if args.as_supervised:
        return cmd_supervised()
    return cmd_interactive(args.freeze, with_http=False)


if __name__ == "__main__":
    sys.exit(main())
