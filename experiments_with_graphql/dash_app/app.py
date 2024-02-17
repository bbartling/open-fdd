
import dash
from dash import dcc, html, Input, Output
from dash.dependencies import ALL, State, Input, Output
from dash.exceptions import PreventUpdate
import plotly.graph_objs as go
import pandas as pd

from graphql_schema import execute_query, brick_mappings

app = dash.Dash(__name__)

app.layout = html.Div(
    [
        html.H1("Sensor Data Visualization"),
        html.Label("Select Time Resolution"),
        dcc.Dropdown(
            id="time_resolution",
            options=[
                {"label": "Daily", "value": "D"},
                {"label": "Weekly", "value": "W"},
                {"label": "Monthly", "value": "M"},
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
            value=["Supply_Air_Flow_Sensor"],  # Default value
            multi=True,  # Allows selecting multiple options
        ),
        html.Div(id="y_axis_choices_container"),
        # Move the button here, above the dcc.Graph
        html.Button("Update Graph", id="update-button", n_clicks=0),
        # Place the dcc.Graph component after the button
        dcc.Graph(id="graph"),
    ]
)


@app.callback(
    Output('y_axis_choices_container', 'children'),
    Input('sensor_type', 'value')
)
def generate_y_axis_dropdowns(sensor_types):
    if not sensor_types:
        return []
    return [
        html.Div([
            html.Label(f"Y-Axis for {sensor_type}"),
            dcc.Dropdown(
                id={'type': 'dynamic-yaxis', 'index': sensor_type},
                options=[
                    {'label': 'Left Y-Axis', 'value': 'left'},
                    {'label': 'Right Y-Axis', 'value': 'right'}
                ],
                value='left',  # Default value
            )
        ]) for sensor_type in sensor_types
    ]


@app.callback(
    Output('graph', 'figure'),
    [Input('update-button', 'n_clicks'),
     Input('time_resolution', 'value')],
    [State('sensor_type', 'value'),
     State({'type': 'dynamic-yaxis', 'index': ALL}, 'value')]
)
def update_graph(n_clicks, time_resolution, sensor_types, y_axis_choices):
    print("Callback triggered")
    
    ctx = dash.callback_context

    if not ctx.triggered:
        raise PreventUpdate

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if trigger_id == 'update-button' and n_clicks == 0:
        raise PreventUpdate

    query_field_map = {
        'D': 'averageByDay',
        'W': 'averageByWeek',
        'M': 'averageByMonth'
    }
    query_field = query_field_map.get(time_resolution)
    
    time_res_title = {
        'D': 'Daily',
        'W': 'Weekly',
        'M': 'Monthly'
    }.get(time_resolution, 'Time')

    x_column = 'day' if time_resolution == 'D' else 'week' if time_resolution == 'W' else 'month'
    fig = go.Figure()

    for sensor_type, y_axis_choice in zip(sensor_types, y_axis_choices):
        query = f'{{ {query_field}(sensorName: "{sensor_type}") {{ {x_column} average }} }}'
        print(f"Generated query for {sensor_type}: {query}")  # Print generated queries
        data = execute_query(query)
        print(f"Data for {sensor_type}: {data}")  # Debug print

        if data and query_field in data:
            df = pd.DataFrame(data[query_field])
            yaxis = 'y2' if y_axis_choice == 'right' else 'y1'
            axis_label = " (Right)" if y_axis_choice == 'right' else " (Left)"
            fig.add_trace(go.Scatter(
                x=df[x_column], y=df['average'], mode='lines',
                name=f"{sensor_type}{axis_label}",  # Append axis label to the name
                yaxis=yaxis
            ))
        else:
            print(f"No data for {sensor_type}")  # Debug print

    fig.update_layout(
        # Remove xaxis_title if it's now redundant
        # xaxis_title="",
        yaxis=dict(title='', side='left', showgrid=False),
        yaxis2=dict(title='', side='right', overlaying='y', showgrid=False),
        title=f'Average Sensor Readings over Time ({time_res_title} Averaged Data)',
        title_x=0.5  # Center the title
    )

    return fig



if __name__ == '__main__':
    app.run_server(debug=True)
