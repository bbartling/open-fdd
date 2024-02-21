import dash
from dash import dcc, html, Input, Output
from dash.dependencies import ALL, State, Input, Output
from dash.exceptions import PreventUpdate
import plotly.express as px
import plotly.graph_objs as go
import pandas as pd
import numpy as np

from graphql_schema.graphql_logic import execute_query, brick_mappings


app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H1("Sensor Data Visualization"),
        html.Label("Select Time Resolution"),
        dcc.Dropdown(
            id="time_resolution",
            options=[
                {"label": "Hourly", "value": "H"},
                {"label": "Daily", "value": "D"},
                {"label": "Weekly", "value": "W"},
                {"label": "Monthly", "value": "M"},
                {"label": "Raw", "value": "R"},
            ],
            value="M",  # Default value
        ),
        html.Label("Select Sensor(s)"),
        dcc.Dropdown(
            id="sensor_type",
            options=[
                {"label": value, "value": value}
                for key, value in brick_mappings.items()
            ],
            value=["Outside_Air_Temperature_Sensor"],  # Default value
            multi=True,  # Allows selecting multiple options
        ),
        html.Div(id="y_axis_choices_container"),
        html.Div(
            id="fan_status_filter_container"
        ),  # Container for fan status filter checkboxes
        html.Button("Update Graph", id="update-button", n_clicks=0),
        dcc.Graph(id="graph"),
        html.Div(
            [
                html.Button(
                    "Update Motor Run Time Graph",
                    id="update-motor-run-time-button",
                    n_clicks=0,
                ),
                dcc.Graph(id="motor-run-time-graph"),
            ],
            style={"margin-top": "20px"},  # Add some space between components
        ),
    ]
)


@app.callback(
    Output("motor-run-time-graph", "figure"),
    [Input("update-motor-run-time-button", "n_clicks")],
    [State("sensor_type", "value")],
)
def update_motor_run_time_graph(n_clicks, sensor_types):
    if n_clicks == 0:
        raise PreventUpdate

    # Assuming you want to use the first sensor type for the motor run time
    sensor_name = sensor_types[0] if sensor_types else None

    if sensor_name:
        # Update your query to use the string sensor name
        query = f'{{ dailyMotorRunTime(sensorName: "{sensor_name}") {{ day runTimeHours }} }}'
        data = execute_query(query)

        if data and "dailyMotorRunTime" in data:
            df = pd.DataFrame(data["dailyMotorRunTime"])
            fig = px.line(
                df, x="day", y="runTimeHours", title="Daily Motor Run Time (Hours)"
            )
            return fig

    return go.Figure()


@app.callback(
    Output("y_axis_choices_container", "children"), Input("sensor_type", "value")
)
def generate_y_axis_dropdowns(sensor_types):
    if not sensor_types:
        return []
    return [
        html.Div(
            [
                html.Label(f"Y-Axis for {sensor_type}"),
                dcc.Dropdown(
                    id={"type": "dynamic-yaxis", "index": sensor_type},
                    options=[
                        {"label": "Left Y-Axis", "value": "left"},
                        {"label": "Right Y-Axis", "value": "right"},
                    ],
                    value="left",  # Default value
                ),
            ]
        )
        for sensor_type in sensor_types
    ]


@app.callback(
    Output("fan_status_filter_container", "children"), Input("sensor_type", "value")
)
def generate_fan_status_filter(sensor_types):
    if not sensor_types:
        return []
    return [
        html.Div(
            [
                dcc.Checklist(
                    options=[
                        {
                            "label": f'Filter {sensor_type.replace("_", " ").lower()} for when fan is running',
                            "value": "FR",
                        }
                    ],
                    value=[],
                    id={"type": "dynamic-fan-status", "index": sensor_type},
                )
            ]
        )
        for sensor_type in sensor_types
    ]


@app.callback(
    Output("graph", "figure"),
    [Input("update-button", "n_clicks"), Input("time_resolution", "value")],
    [
        State("sensor_type", "value"),
        State({"type": "dynamic-yaxis", "index": ALL}, "value"),
        State({"type": "dynamic-fan-status", "index": ALL}, "value"),
    ],
)
def update_graph(n_clicks, time_resolution, sensor_types, y_axis_choices, fan_statuses):
    print("Callback triggered")

    ctx = dash.callback_context

    if not ctx.triggered:
        raise PreventUpdate

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "update-button" and n_clicks == 0:
        raise PreventUpdate

    query_field_map = {
        "H": "averageByHour",
        "D": "averageByDay",
        "W": "averageByWeek",
        "M": "averageByMonth",
        "R": "rawData",
    }
    query_field = query_field_map.get(time_resolution)

    time_res_title = {
        "H": "Hourly",
        "D": "Daily",
        "W": "Weekly",
        "M": "Monthly",
        "R": "Raw",
    }.get(time_resolution, "Time")

    x_column = (
        "hour"
        if time_resolution == "H"
        else (
            "day"
            if time_resolution == "D"
            else (
                "week"
                if time_resolution == "W"
                else "month" if time_resolution == "M" else "timestamp"
            )
        )
    )

    fig = go.Figure()

    # Initialize an empty list for fan status
    fan_status_list = ["FR" in status for status in fan_statuses]

    for sensor_type, y_axis_choice, is_fan_running in zip(
        sensor_types, y_axis_choices, fan_status_list
    ):
        # Correctly format the boolean value for the GraphQL query
        # JSON doesnt like True as bool like python does
        fan_running_str = str(
            is_fan_running
        ).lower()  # Convert Python bool to lowercase string

        # Construct the GraphQL query based on the time resolution
        if time_resolution == "H":  # For hourly data
            query = f'{{ averageByHour(sensorName: "{sensor_type}", fanRunning: {fan_running_str}) {{ hour average }} }}'
        elif time_resolution == "D":  # For daily data
            query = f'{{ averageByDay(sensorName: "{sensor_type}", fanRunning: {fan_running_str}) {{ day average }} }}'
        elif time_resolution == "W":  # For weekly data
            query = f'{{ averageByWeek(sensorName: "{sensor_type}", fanRunning: {fan_running_str}) {{ week average }} }}'
        elif time_resolution == "M":  # For monthly data
            query = f'{{ averageByMonth(sensorName: "{sensor_type}", fanRunning: {fan_running_str}) {{ month average }} }}'
        elif time_resolution == "R":  # For raw data
            query = f'{{ rawData(sensorName: "{sensor_type}", fanRunning: {fan_running_str}) {{ timestamp value }} }}'
        else:
            # Handle other cases or throw an error
            raise ValueError("Invalid time resolution")

        print(f"Generated query for {sensor_type}: {query}")  # Print generated queries
        data = execute_query(query)
        print(f"Data for {sensor_type}: {data}")  # Debug print

        if data and query_field in data:
            df = pd.DataFrame(data[query_field])

            # Determine the y-axis data and process it based on the time resolution
            if time_resolution == "R":
                if 'value' in df.columns:
                    # Handling Raw data
                    df["value"].replace(-9999.99, np.nan, inplace=True)
                    y_data = df["value"]
                    x_data = df[x_column]
            else:
                # Handling Averaged data
                if 'average' in df.columns:
                    df["average"].replace(-9999.99, np.nan, inplace=True)
                    y_data = df["average"]
                    x_data = df[x_column]
                else:
                    raise ValueError(f"'average' column not found in response for {sensor_type}")

            # Define the y-axis side and label based on user's choice
            yaxis = "y2" if y_axis_choice == "right" else "y1"
            axis_label = " (Right)" if y_axis_choice == "right" else " (Left)"

            # Add trace to the figure
            fig.add_trace(
                go.Scatter(
                    x=x_data,
                    y=y_data,
                    mode="lines",
                    connectgaps=False,  # Do not connect the gaps caused by NaN values
                    name=f"{sensor_type}{axis_label}",
                    yaxis=yaxis,
                )
            )

        else:
            print(f"No data for {sensor_type}")  # Debug print

    fig.update_layout(
        # Remove xaxis_title if it's now redundant
        # xaxis_title="",
        yaxis=dict(title="", side="left", showgrid=False),
        yaxis2=dict(title="", side="right", overlaying="y", showgrid=False),
        title=f"Average Sensor Readings over Time ({time_res_title} Averaged Data)",
        title_x=0.5,  # Center the title
    )

    return fig

