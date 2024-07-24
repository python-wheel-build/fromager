import click

from fromager import context, server


@click.command()
@click.option(
    "-p",
    "--port",
    type=int,
    default=8080,
    help="the port to listen on",
)
@click.option(
    "-i",
    "--ip",
    "--address",
    "address",
    default="localhost",
    help="the address to listen on, defaults to localhost",
)
@click.pass_obj
def wheel_server(
    wkctx: context.WorkContext,
    port: int,
    address: str,
) -> None:
    "Start a web server to server the local wheels-repo"
    server.update_wheel_mirror(wkctx)
    t = server.run_wheel_server(
        wkctx,
        address=address,
        port=port,
    )
    print(f"Listening on {wkctx.wheel_server_url}")
    t.join()
