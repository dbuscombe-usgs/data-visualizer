# Standard library importspn
import os

# External dependencies imports
import param
import panel as pn
import geoviews as gv
import geoviews.tile_sources as gts
from geoviews import opts
import rioxarray as rxr
import pandas as pd
import geopandas as gpd
import cartopy.crs as ccrs
import holoviews as hv
from bokeh.palettes import Bokeh, Set2
from shapely.geometry import Point

class DataMap(param.Parameterized):
    # -------------------------------------------------- Parameters with GUI Widgets --------------------------------------------------
    basemap = param.Selector(label = "Basemap")
    categories = param.ListSelector(label = "Data Categories")
    transects = param.ListSelector(label = "Transects")

    # -------------------------------------------------- Constructor --------------------------------------------------
    def __init__(self, data_dir_path: str, latitude_col_names: list[str], longitude_col_names: list[str], template: pn.template, colors: dict = {}, basemap_options: dict = {"Default": gts.OSM}, **params) -> None:
        """
        Creates a new instance of the DataMap class with its instance variables.

        Args:
            data_dir_path (str): Path to the directory containing all the data category subfolders and their data files
            latitude_col_names (list[str]): Possible names of the column containing the latitude of each data point
            longitude_col_names (list[str]): Possible names of the column containing the longitude of each data point
            template (panel.template): Data visualizer app's template
            colors (dict): Optional dictionary mapping each data category name (keys) to a color (values), which will be the color of its data points
            basemap_options (dict): Optional dictionary mapping each basemap name (keys) to a basemap WMTS (web mapping tile source) layer (values)
        """
        super().__init__(**params)

        # -------------------------------------------------- Constants --------------------------------------------------
        self._data_dir_path = data_dir_path
        self._all_lat_cols = latitude_col_names
        self._all_long_cols = longitude_col_names
        self._app_template = template
        self._all_point_markers = ["o", "^", "s", "d", "x", ">", "*", "v", "+", "<"]
        
        # _transects_folder_name = Name of the folder containing files with transect data
        self._transects_folder_name = "Transects"
        # _create_own_transect_option = Name of the option for the user to create their own transect
        self._create_own_transect_option = "Create My Own Transect"
        # _point_type_col_name = Name of the column that stores the type of transect point (either start or end)
        self._point_type_col_name = "Point Type"
        # _geodata_folder_name = Name of the folder containing GeoJSON/GeoTIFF files that were created by georeferencing data files (txt, csv, asc)
        # ^ allows data to load faster onto the map
        self._geodata_folder_name = "GeoData"
        
        # _crs = custom coordinate reference system for the projected data
        # ^ can be created from a dictionary of PROJ parameters
        # ^ https://scitools.org.uk/cartopy/docs/latest/reference/generated/cartopy.crs.CRS.html#cartopy.crs.CRS.__init__
        self._crs = ccrs.CRS({
            "proj": "lcc",
            "lat_1": 47.5,
            "lat_2": 48.73333333333333,
            "lon_0": -120.8333333333333,
            "lat_0": 47.0,
            "x_0": 500000.0,
            "y_0": 0.0,
            "units": "m",
            "datum": "NAD83",
            "ellps": "GRS80",
            "no_defs": True,
            "type": "crs"
        })
        # _epsg = publicly registered coordinate system for the projected data
        # ^ should be close, if not equivalent, to the custom CRS defined above (_crs)
        self._epsg = ccrs.epsg(32148)

        # -------------------------------------------------- Internal Class Properties --------------------------------------------------
        # _created_plots = dictionary mapping each filename (keys) to its created plot (values)
        self._created_plots = {}
        
        # _all_basemaps = dictionary mapping each basemap name (keys) to a basemap WMTS (web mapping tile source) layer (values)
        self._all_basemaps = basemap_options
        # _selected_basemap_plot = WMTS (web mapping tile source) layer containing the user's selected basemap
        self._selected_basemap_plot = basemap_options[list(basemap_options.keys())[0]]
        
        # _all_categories = list of data categories (subfolders in the root data directory -> excludes transects)
        self._all_categories = [file for file in os.listdir(data_dir_path) if os.path.isdir(data_dir_path + "/" + file) and (file != self._transects_folder_name)]
        # _category_colors = dictionary mapping each data category (keys) to a color (values), which will be used for the color of its point plots
        self._category_colors = {}
        # _category_markers = dictionary mapping each data category (keys) to a marker (values), which will be used for the marker of its point plots
        self._category_markers = {}
        # _selected_categories_plot = overlay of point plots for each data category selected by the user
        # ^ None if the no data files were provided by the user or the user didn't select any data categories
        self._selected_categories_plot = None
        
        # _all_transect_files = list of files containing transects to display on the map
        self._all_transect_files = []
        if os.path.isdir(data_dir_path + "/" + self._transects_folder_name):
            transects_dir_path = data_dir_path + "/" + self._transects_folder_name
            self._all_transect_files = [file for file in os.listdir(transects_dir_path) if os.path.isfile(os.path.join(transects_dir_path, file))]
        # _transect_colors = dictionary mapping each transect file (keys) to a color (values), which will be used for the color of its path plots
        self._transect_colors = {}
        # _selected_transects_plot = overlay of path plots if the user selected one or more transect files to display on the map
        # ^ None if the user didn't provide any transect files or the user didn't select to display a transect file
        self._selected_transects_plot = None

        # _tapped_data_streams = dictionary mapping each transect filename (keys) to a selection stream (values), which saves the file's most recently clicked data element (path) on the map
        self._tapped_data_streams = {file: hv.streams.Selection1D(source = None, rename = {"index": file}) for file in self._all_transect_files}
        # _time_series_plot = time-series plot for data collected along the most recently clicked transect (path)
        self._time_series_plot = gv.DynamicMap(self._create_time_series_plot, streams = list(self._tapped_data_streams.values()))
        # _clicked_transect_pipe = pipe stream that sends info about the most recently clicked transect
        self._clicked_transect_pipe = hv.streams.Pipe(data = {})
        # _clicked_transect_table = table containing information about the clicked transect's start and end points
        self._clicked_transect_table = gv.DynamicMap(self._create_clicked_transect_table, streams = [self._clicked_transect_pipe])

        # _user_transect_plot = predefined path plot if the user wanted to create their own transect to display on the map
        self._user_transect_plot = gv.Path(
            data = [[(296856.9100, 131388.7700), (296416.5400, 132035.8500)]],
            crs = self._epsg
        ).opts(active_tools = ["poly_draw"])
        # self._user_transect_plot = hv.Curve(data = np.array([[(-123.5688, 48.1523), (-123.5626, 48.1476)]])).opts(active_tools = ["point_draw"])
        # self._user_transect_plot = hv.Points(
        #     data = np.array([[-123.5688, 48.1523], [-123.5626, 48.1476]])
        # ).opts(active_tools = ["point_draw"], color = "black")
        # self._user_transect_plot = hv.Curve([]).opts(
        #     active_tools = ["point_draw"],
        #     color = "black"
        # )
        # _edit_user_transect_stream = stream that allows user to move the start and end points of their own transect
        self._edit_user_transect_stream = hv.streams.PolyDraw(
            source = self._user_transect_plot,
            num_objects = 1,
            drag = True,
            styles = {"line_color": ["black"], "line_width": [5]},
            show_vertices = True,
            vertex_style = {"fill_color": "black"}
        )
        # self._edit_user_transect_stream = hv.streams.PointDraw(source = self._user_transect_plot, num_objects = 2)
        # self._edit_user_transect_stream = hv.streams.CurveEdit(
        #     # data = self._user_transect_plot.columns(),
        #     source = self._user_transect_plot,
        #     num_objects = 2,
        #     add = False,
        #     style = {"color": "black", "size": 10}
        # )

        # -------------------------------------------------- Widget and Plot Options --------------------------------------------------
        # Set basemap widget's options.
        self.param.basemap.objects = basemap_options.keys()

        # Set data category widget's options.
        self._categories_multichoice = pn.widgets.MultiChoice.from_param(
            parameter = self.param.categories,
            options = self._all_categories,
            placeholder = "Choose one or more data categories to display",
            solid = False
        )

        # Set transect widget's options.
        self._transects_multichoice = pn.widgets.MultiChoice.from_param(
            parameter = self.param.transects,
            options = self._all_transect_files + [self._create_own_transect_option],
            placeholder = "Choose one or more transect files to display",
            solid = False
        )

        # Set color and marker for each data category.
        palette_colors = Bokeh[8]
        total_palette_colors, total_markers = len(palette_colors), len(self._all_point_markers)
        for i, category in enumerate(self._all_categories):
            # Assign the color that the user chose, if provided.
            if category in colors:
                self._category_colors[category] = colors[category]
            # Else assign a color from the Bokeh palette.
            else:
                self._category_colors[category] = palette_colors[i % total_palette_colors]
            # Assign a marker.
            self._category_markers[category] = self._all_point_markers[i % total_markers]
        # Set color for each transect option.
        for i, transect_option in enumerate(self._transects_multichoice.options):
            self._transect_colors[transect_option] = palette_colors[(len(category) + i) % total_palette_colors]

    # -------------------------------------------------- Private Class Methods --------------------------------------------------
    def _create_data_points_geojson(self, file_path: str, geojson_path: str) -> None:
        """
        Creates and saves a GeoJSON file containing Points for each data point in the given dataframe.
        
        Args:
            file_path (str): Path to the file containing data points
            geojson_path (str): Path to the newly created GeoJSON file
        """
        # Read the data file as a DataFrame.
        dataframe = pd.read_csv(file_path)
        [latitude_col] = [col for col in dataframe.columns if col in self._all_lat_cols]
        [longitude_col] = [col for col in dataframe.columns if col in self._all_long_cols]
        # Convert the DataFrame into a GeoDataFrame.
        geodataframe = gpd.GeoDataFrame(
            data = dataframe,
            geometry = gpd.points_from_xy(
                x = dataframe[longitude_col],
                y = dataframe[latitude_col],
                crs = "EPSG:4326"
            )
        )
        # Save the GeoDataFrame into a GeoJSON file to skip converting the data file again.
        geodataframe.to_file(geojson_path, driver = "GeoJSON")
    
    def _plot_geojson_points(self, geojson_file_path: str, data_category: str) -> gv.Points:
        """
        Creates a point plot from a GeoJSON file containing Points.

        Args:
            geojson_file_path (str): Path to the GeoJSON file containing Points
            data_category (str): Name of the data category that the data file belongs to
        """
        # Read the GeoJSON as a GeoDataFrame.
        geodataframe = gpd.read_file(geojson_file_path)
        latitude_col, longitude_col, non_lat_long_cols = None, None, []
        for col in geodataframe.columns:
            if col in self._all_lat_cols: latitude_col = col
            elif col in self._all_long_cols: longitude_col = col
            elif col != "geometry": non_lat_long_cols.append(col)
        # Create a point plot with the GeoDataFrame.
        point_plot = gv.Points(
            data = geodataframe,
            kdims = [longitude_col, latitude_col],
            vdims = non_lat_long_cols,
            label = data_category
        ).opts(
            color = self._category_colors[data_category],
            marker = self._category_markers[data_category],
            tools = ["hover"],
            size = 10, muted_alpha = 0.01
        )
        return point_plot
    
    def _convert_ascii_grid_data_into_geotiff(self, file_path: str, geotiff_path: str) -> None:
        """
        Converts an ASCII grid file into a GeoTIFF file.

        Args:
            file_path (str): Path to the ASCII grid file
            geotiff_path (str): Path to the newly created GeoTIFF file
        """
        if not os.path.exists(geotiff_path):
            dataset = rxr.open_rasterio(file_path)
            # Add custom projection based on the Elwha data's metadata.
            dataset.rio.write_crs(self._crs, inplace = True)
            # Create the GeoData folder if it doesn't exist yet.
            geodata_dir_path, _ = os.path.split(geotiff_path)
            if not os.path.isdir(geodata_dir_path): os.makedirs(geodata_dir_path)
            # Save the data as a GeoTIFF.
            dataset.rio.to_raster(
                raster_path = geotiff_path,
                driver = "GTiff"
            )

    def _create_data_plot(self, filename: str, category: str) -> None:
        """
        Creates a point/image plot containing the given file's data.

        Args:
            filename (str): Name of the file containing data
            category (str): Name of the data category that the file belongs to
        """
        # Read the file and create a plot from it.
        file_path = self._data_dir_path + "/" + category + "/" + filename
        [name, extension] = os.path.splitext(filename)
        extension = extension.lower()
        category_geodata_dir_path = self._data_dir_path + "/" + category + "/" + self._geodata_folder_name
        plot = None
        if extension in [".csv", ".txt"]:
            # Convert the data file into a new GeoJSON (if not created yet).
            geojson_path = category_geodata_dir_path + "/" + name + ".geojson"
            if not os.path.exists(geojson_path):
                # Create the GeoData folder if it doesn't exist yet.
                if not os.path.isdir(category_geodata_dir_path): os.makedirs(category_geodata_dir_path)
                # Create a FeatureCollection of Points based on the data file.
                self._create_data_points_geojson(file_path, geojson_path)
            # Create a point plot with the GeoJSON.
            plot = self._plot_geojson_points(geojson_path, category)
        elif extension == ".asc":
            geotiff_path = category_geodata_dir_path + "/" + name + ".tif"
            # Convert ASCII grid file into a new GeoTIFF (if not created yet).
            self._convert_ascii_grid_data_into_geotiff(file_path, geotiff_path)
            # Create an image plot with the GeoTIFF.
            plot = gv.load_tiff(
                geotiff_path,
                vdims = "Elevation (meters)",
                nan_nodata = True
            ).opts(
                cmap = "Turbo",
                tools = ["hover"],
                alpha = 0.5
            )
        if plot is None:
            print("Error displaying", name + extension, "as a point/image plot:", "Input files with the", extension, "file format are not supported yet.")
        else:
            # Save the created plot.
            self._created_plots[filename] = plot

    def _create_transects_geojson(self, file_path: str, geojson_path: str) -> None:
        """
        Creates and saves a GeoJSON file containing LineStrings for each transect in the given transect file.

        Args:
            file_path (str): Path to the file containing transect data
            geojson_path (str): Path to the newly created GeoJSON file
        """
        features_list = []
        with open(file_path, "r") as file:
            transect_feature = None
            for line in file:
                [point_id, x, y, _] = line.split(",")
                point = [float(x), float(y)]
                if transect_feature is None:
                    # Initialize a new transect feature.
                    id = int("".join([char for char in point_id if char.isdigit()]))
                    transect_feature = {
                        "type": "Feature",
                        "properties": {"Transect ID": id},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": []
                        }
                    }
                    # Add the transect's start point.
                    transect_feature["geometry"]["coordinates"].append(point)
                    transect_feature["properties"]["Start Point (meters)"] = "({}, {})".format(x, y)
                else:
                    # Add the transect's end point.
                    transect_feature["geometry"]["coordinates"].append(point)
                    transect_feature["properties"]["End Point (meters)"] = "({}, {})".format(x, y)
                    # Save the transect to the FeatureCollection.
                    features_list.append(transect_feature)
                    # Reset the feature for the next transect.
                    transect_feature = None
        # Convert the FeatureCollection into a GeoJSON.
        geodataframe = gpd.GeoDataFrame.from_features(
            {"type": "FeatureCollection", "features": features_list},
            crs = self._crs
        )
        # Save the GeoJSON file to skip converting the data file again.
        geodataframe.to_file(geojson_path, driver = "GeoJSON")
    
    def _plot_geojson_linestrings(self, geojson_file_path: str, filename: str) -> gv.Path:
        """
        Creates a path plot from a GeoJSON file containing LineStrings.

        Args:
            geojson_file_path (str): Path to the GeoJSON file containing LineStrings
            filename (str): Name of the transect file that corresponds to the returned path plot
        """
        geodataframe = gpd.read_file(geojson_file_path)
        path_plot = gv.Path(
            data = geodataframe,
            crs = self._epsg,
            label = "{}: {}".format(self._transects_folder_name, filename)    # HoloViews 2.0: Paths will be in legend by default when a label is specified (https://github.com/holoviz/holoviews/issues/2601)
        ).opts(
            color = self._transect_colors[filename],
            tools = ["hover", "tap"]
        )
        return path_plot
    
    def _create_path_plot(self, filename: str) -> None:
        """
        Creates a path plot containing the given file's paths.

        Args:
            filename (str): Name of the file containing paths
        """
        # Read the given file.
        file_path = self._data_dir_path + "/" + self._transects_folder_name + "/" + filename
        [name, extension] = os.path.splitext(filename)
        extension = extension.lower()
        transects_geodata_dir_path = self._data_dir_path + "/" + self._transects_folder_name + "/" + self._geodata_folder_name
        # Create a path plot from the given file.
        plot = None
        if extension == ".txt":
            geojson_path = transects_geodata_dir_path + "/" + name + ".geojson"
            # Convert the data file into a new GeoJSON (if not created yet).
            if not os.path.exists(geojson_path):
                # Create the GeoData folder if it doesn't exist yet.
                if not os.path.isdir(transects_geodata_dir_path): os.makedirs(transects_geodata_dir_path)
                # Create a FeatureCollection of LineStrings based on the data file.
                self._create_transects_geojson(file_path, geojson_path)
            # Create a path plot with the GeoJSON.
            plot = self._plot_geojson_linestrings(geojson_path, filename)
        # Save the path plot, if created.
        if plot is None:
            print("Error displaying", name + extension, "as a path plot:", "Input files with the", extension, "file format are not supported yet.")
        else:
            self._created_plots[filename] = plot

    def _create_clicked_transect_table(self, data: dict) -> hv.Table:
        """
        Creates a table containing information about the clicked transect's start and end points.

        Args:
            data (dict): Dictionary mapping each data column (keys) to a list of values for that column (values)
        """
        # Return the table with updated transect data.
        return hv.Table(
            data = data,
            kdims = [self._point_type_col_name],
            vdims = [col for col in list(data.keys()) if col != self._point_type_col_name]
        ).opts(
            title = "Selected Transect's Data",
            editable = False, fit_columns = True
        )

    def _get_data_along_transect(self, data_file_path: str, transect_points: list[list[float]], data_col_name: str, dist_col_name: str, new_long_col_name: str, new_lat_col_name: str) -> pd.DataFrame:
        """
        Gets all data that was collected along the given transect and returns that data as a dataframe.
        Returns None if no data could be extracted with the given transect.

        Args:
            data_file_path (str): 
            transect_points (list[list[float]]):
            data_col_name (str):
            dist_col_name (str): 
            new_long_col_name (str):
            new_lat_col_name (str):
        """
        data_dir_path, data_file = os.path.split(data_file_path)
        name, extension = os.path.splitext(data_file)
        extension = extension.lower()
        if extension == ".asc":
            geotiff_path = data_dir_path + "/" + self._geodata_folder_name + "/" + name + ".tif"
            # Convert ASCII grid file into a new GeoTIFF (if not created yet).
            self._convert_ascii_grid_data_into_geotiff(data_file_path, geotiff_path)
            # Clip data collected along the clicked transect from the given data file.
            dataset = rxr.open_rasterio(geotiff_path)
            try:
                clipped_dataset = dataset.rio.clip(
                    geometries = [{
                        "type": "LineString",
                        "coordinates": transect_points
                    }],
                    from_disk = True
                )
            except ValueError:
                # Given transect doesn't overlap data file, so return None early since the clipped dataset would be empty.
                return None
            # Convert data into a DataFrame for easier plotting.
            clipped_dataset = clipped_dataset.squeeze().drop("spatial_ref").drop("band")
            clipped_dataset.name = data_col_name
            clipped_dataframe = clipped_dataset.to_dataframe().reset_index()
            no_data_val = clipped_dataset.attrs["_FillValue"]
            clipped_dataframe = clipped_dataframe[clipped_dataframe[data_col_name] != no_data_val]
            clipped_geodataframe = gpd.GeoDataFrame(
                data = clipped_dataframe,
                geometry = gpd.points_from_xy(
                    x = clipped_dataframe["x"],
                    y = clipped_dataframe["y"],
                    crs = self._epsg
                )
            )
            # Calculate each point's distance from the transect's start point.
            transect_start_point = Point(transect_points[0])
            clipped_geodataframe[dist_col_name] = [point.distance(transect_start_point) for point in clipped_geodataframe.geometry]
            clipped_data_dataframe = clipped_geodataframe.drop(columns = "geometry").rename(
                columns = {
                    "x": new_long_col_name,
                    "y": new_lat_col_name
                }
            ).reset_index(drop = True)
            return clipped_data_dataframe
        # Return None if there's currently no implementation to extract data from the data file yet.
        print("Error extracting data along a transect from", data_file, ":", "Files with the", extension, "file format are not supported yet.")
        return None

    def _create_time_series_plot(self, **params: dict) -> hv.Overlay:
        """
        Creates a time-series plot for data collected along a clicked transect on the map.

        Args:
            params (dict): Dictionary mapping each transect filename (keys) to a list containing the indices of selected/clicked/tapped transects (values) from its transect file
        """
        # print("Selection1D streams' parameters:", params)
        new_long_col_name = "Easting (meters)"
        new_lat_col_name = "Northing (meters)"
        data_col_name = "Elevation"
        dist_col_name = "Distance from Shore"
        x_axis_col = dist_col_name
        y_axis_col = data_col_name
        other_val_cols = [new_long_col_name, new_lat_col_name]
        overlay_options = opts.Overlay(
            title = "Time-Series of Data Collected Along the Selected Transect",
            xlabel = "Across-Shore Distance (m)",
            ylabel = "Elevation (m)",
            active_tools = ["pan", "wheel_zoom"],
            toolbar = None, show_legend = True,
            height = 500, responsive = True, padding = 0.1
        )
        # Assign styles for data in the time-series plot.
        data_dir_path = "./data/Elwha/Digital Elevation Models (DEMs)"
        point_colors = list(Set2[8])
        curve_styles = ["solid", "dashed", "dotted", "dotdash", "dashdot"]
        total_colors, total_styles, total_markers = len(point_colors), len(curve_styles), len(self._all_point_markers)
        data_files, file_color, file_line, file_marker, i = [], {}, {}, {}, 0
        for file in os.listdir(data_dir_path):
            if os.path.isfile(os.path.join(data_dir_path, file)):
                data_files.append(file)
                file_color[file] = point_colors[i % total_colors]
                file_line[file] = curve_styles[i % total_styles]
                file_marker[file] = self._all_point_markers[i % total_markers]
                i += 1
        # Find the user's clicked/selected transect(s).
        for file in self._all_transect_files:
            clicked_transect_indices = params[file]
            num_clicked_transects = len(clicked_transect_indices)
            # Reset transect file's Selection1D stream parameter to its default value (empty list []).
            self._tapped_data_streams[file].reset()
            if num_clicked_transects == 1:
                # Open the app's modal to display the time-series plot.
                self._app_template.open_modal()
                # Get the user's clicked transect.
                [transect_index] = clicked_transect_indices
                transects_file_plot = self._created_plots[file]
                transect_file_paths = transects_file_plot.split()
                clicked_transect_data = transect_file_paths[transect_index].columns(dimensions = ["Longitude", "Latitude", "Transect ID"])
                # Rename GeoViews' default coordinate column names.
                clicked_transect_data_dict = {}
                for col, values in clicked_transect_data.items():
                    if col == "Longitude": col = new_long_col_name
                    elif col == "Latitude": col = new_lat_col_name
                    # Convert the numpy array of column values into a Python list to make it easier to iterate over the values.
                    clicked_transect_data_dict[col] = values.tolist()
                # Add a new "Point Type" column to differentiate the transect points.
                clicked_transect_data_dict[self._point_type_col_name] = ["start", "end"]
                # Update the transect pipe stream's data parameter and trigger an event in order to update the transect's data table.
                self._clicked_transect_pipe.event(data = clicked_transect_data_dict)
                # For each data file, plot its data collected along the clicked transect.
                # plots_dict = {}
                plot = None
                transect_points = list(zip(
                    clicked_transect_data_dict[new_long_col_name],
                    clicked_transect_data_dict[new_lat_col_name],
                    strict = True
                ))
                for file in data_files:
                    # Clip data along the selected transect for each data file.
                    clipped_dataframe = self._get_data_along_transect(
                        data_file_path = data_dir_path + "/" + file,
                        transect_points = transect_points,
                        data_col_name = data_col_name,
                        dist_col_name = dist_col_name,
                        new_long_col_name = new_long_col_name,
                        new_lat_col_name = new_lat_col_name
                    )
                    if clipped_dataframe is not None:
                        # Plot clipped data.
                        clipped_data_curve_plot = hv.Curve(
                            data = clipped_dataframe,
                            kdims = x_axis_col,
                            vdims = y_axis_col,
                            label = file
                        ).opts(
                            color = file_color[file],
                            line_dash = file_line[file]
                        )
                        clipped_data_point_plot = hv.Points(
                            data = clipped_dataframe,
                            kdims = [x_axis_col, y_axis_col],
                            vdims = other_val_cols,
                            label = file
                        ).opts(
                            color = file_color[file],
                            marker = file_marker[file],
                            tools = ["hover"],
                            size = 10
                        )
                        # Add the data file's plot to the overlay plot.
                        clipped_data_plot = clipped_data_curve_plot * clipped_data_point_plot
                        if plot is None: plot = clipped_data_plot
                        else: plot = plot * clipped_data_plot
                        # plots_dict[file] = clipped_data_plot
                # # Return the overlay plot containing data collected along the transect for all data files.
                # print("overlay", plots_dict)
                # # if plots_dict: return hv.NdOverlay(overlays = plots_dict).opts(data_plot_options)
                # if plots_dict:
                #     plot = hv.Overlay(items = [("", plot) for plot in list(plots_dict.values())]).opts(*plot_options)
                #     print(plot)
                #     return plot
                print("result", plot)
                if plot is not None: return plot.opts(overlay_options)
            elif num_clicked_transects > 1:
                print("Error creating time-series of data: Only 1 transect should be selected but {} were selected.".format(num_clicked_transects))
        # Return an overlay plot with placeholder plots for each data file if a transect has not been selected yet.
        # ^ since DynamicMap requires callback to always return the same element (in this case, Overlay)
        # ^ DynamicMap currently doesn't update plots properly when new plots are added to the initially returned plots, so placeholder/empty plots are created for each data file
        # return hv.NdOverlay(overlays = {"": hv.Curve([])}).opts(overlay_options)
        plot = None
        for file in data_files:
            empty_curve_plot = hv.Curve(data = [], kdims = x_axis_col, vdims = y_axis_col, label = file)
            empty_point_plot = hv.Points(data = [], kdims = [x_axis_col, y_axis_col], vdims = other_val_cols, label = file).opts(tools = ["hover"])
            placeholder_file_plots = empty_curve_plot * empty_point_plot
            if plot is None: plot = placeholder_file_plots
            else: plot = plot * placeholder_file_plots
        return plot.opts(overlay_options)

    @param.depends("basemap", watch = True)
    def _update_basemap_plot(self) -> None:
        """
        Creates basemap WMTS (web mapping tile source) plot whenever the selected basemap name changes.
        """
        # Get the name of the newly selected basemap.
        if self.basemap is None:
            selected_basemap_name = list(self._all_basemaps.keys())[0]
        else:
            selected_basemap_name = self.basemap
        # Create the plot containing the basemap.
        new_basemap_plot = self._all_basemaps[selected_basemap_name]
        # Save basemap plot.
        self._selected_basemap_plot = new_basemap_plot

    @param.depends("categories", watch = True)
    def _update_selected_categories_plot(self) -> None:
        """
        Creates an overlay of data plots whenever the selected data categories change.
        """
        # Only when the widget is initialized and at least one data category is selected...
        if self.categories is not None:
            # Create a plot with data from each selected category that is within the selected datetime range.
            new_data_plot = None
            selected_category_names = self.categories
            for category in self._all_categories:
                category_dir_path = self._data_dir_path + "/" + category
                category_files = [file for file in os.listdir(category_dir_path) if os.path.isfile(os.path.join(category_dir_path, file))]
                for file in category_files:
                    if (category in selected_category_names):# and self._data_within_date_range(file):
                        # Create the selected data's point plot if we never read the file before.
                        if file not in self._created_plots:
                            self._create_data_plot(file, category)
                        # Display the data file's point plot if it was created.
                        # ^ plots aren't created for unsupported files -> e.g. png files don't have data points
                        if file in self._created_plots:
                            if new_data_plot is None:
                                new_data_plot = self._created_plots[file]
                            else:
                                new_data_plot = (new_data_plot * self._created_plots[file])
            # Save overlaid category plots.
            self._selected_categories_plot = new_data_plot

    @param.depends("transects", watch = True)
    def _update_selected_transects_plot(self) -> None:
        """
        Creates an overlay of path plots whenever the selected transect files change.
        """
        # Only when the widget is initialized and at least one transect file is selected...
        if self.transects is not None:
            # Create an overlay of path plots with transects from each selected transect file.
            new_transects_plot = None
            for file in self.transects:
                # Allow user to draw start and end points when they selected to draw their own transect.
                if file == self._create_own_transect_option:
                    # Display an editable curve plot for the user to modify their transect's start and end points.
                    if new_transects_plot is None:
                        new_transects_plot = self._user_transect_plot
                    else:
                        new_transects_plot = (new_transects_plot * self._user_transect_plot)
                else:
                    # Create the selected transect file's path plot if we never read the file before.
                    if file not in self._created_plots:
                        self._create_path_plot(file)
                        # Save the new plot as a source for the transect file's Selection1D stream.
                        self._tapped_data_streams[file].source = self._created_plots[file]
                    # Display the transect file's path plot if it was created.
                    # ^ plots aren't created for unsupported files
                    if file in self._created_plots:
                        if new_transects_plot is None:
                            new_transects_plot = self._created_plots[file]
                        else:
                            new_transects_plot = (new_transects_plot * self._created_plots[file])
            # Save overlaid transect plots.
            self._selected_transects_plot = new_transects_plot

    # -------------------------------------------------- Public Class Methods --------------------------------------------------
    @param.depends("_update_basemap_plot", "_update_selected_categories_plot", "_update_selected_transects_plot")
    def plot(self) -> gv.Overlay:
        """
        Returns selected basemap and data plots as an overlay whenever any of the plots are updated.
        """
        # Overlay the selected plots.
        new_plot = self._selected_basemap_plot
        default_active_tools = ["pan", "wheel_zoom"]
        if self._selected_categories_plot is not None:
            new_plot = (new_plot * self._selected_categories_plot)
        if self._selected_transects_plot is not None:
            new_plot = (new_plot * self._selected_transects_plot)
            # if self._create_own_transect_option in self.transects:
            #     default_active_tools.append("poly_draw")
        # Return the overlaid plots.
        return new_plot.opts(
            xaxis = None, yaxis = None,
            tools = ["zoom_in", "zoom_out", "save"],
            active_tools = default_active_tools,
            toolbar = "above",
            # toolbar = None,
            title = "", show_legend = True
        )

    @property
    def param_widgets(self) -> list[any]:
        """
        Returns a list of parameters (will have default widget) or custom Panel widgets for parameters used in the app.
        """
        widgets = [
            self.param.basemap,
            self._categories_multichoice
        ]
        # If the user provided file(s) containing transects in a subfolder along with the data categories, then display transect widget.
        if len(self._all_transect_files): widgets.append(self._transects_multichoice)
        return widgets

    @property
    def time_series_plot(self) -> gv.DynamicMap:
        """
        Returns a time-series plot for data collected near the selected transect on the map.
        """
        return self._time_series_plot
    
    # @param.depends("_create_clicked_transect_table")
    @property
    def clicked_transect_data(self) -> pn.widgets.DataFrame:
        """
        Returns a table for the selected transect on the map.
        """
        # table_dynamic_map_vals = self._clicked_transect_table.values()
        # if len(table_dynamic_map_vals):
        #     holoviews_table = table_dynamic_map_vals[0]
        #     print(holoviews_table)
        #     # Create a pandas dataframe containing the clicked transect's data.
        #     col_names = holoviews_table.dimensions(
        #         selection = "all",
        #         label = "name"
        #     )
        #     print(col_names)
        #     clicked_transect_dataframe = holoviews_table.dframe(
        #         dimensions = col_names,
        #         # multi_index = True
        #     )
        #     # dict = holoviews_table.columns(dimensions = ["Point Type", "Easting (meters)", "Northing (meters)", "Transect ID"])
        #     # print(dict)
        #     # clicked_transect_dataframe = pd.DataFrame(dict)
        #     print("table dataframe", clicked_transect_dataframe)

        # # Return a customized Panel DataFrame widget.
        # return pn.widgets.DataFrame(
        #     self._clicked_transect_dataframe,
        #     name = "Selected Transect's Data",
        #     show_index = True, auto_edit = False, text_align = "center"
        # )
        
        # print(self._clicked_transect_table.last)
        # if self._clicked_transect_table.last is None:
        #     return self._clicked_transect_table
        # else:
        #     print("dframe", self._clicked_transect_table.last.dframe())
        #     widget = pn.widgets.DataFrame(
        #         value = self._clicked_transect_table.last.dframe(),
        #         name = "Selected Transect's Data",
        #         show_index = True, auto_edit = False, text_align = "center"
        #     )
        #     print(widget)
        return self._clicked_transect_table

class Application(param.Parameterized):
    # -------------------------------------------------- Main Components --------------------------------------------------
    data_map = param.ClassSelector(class_ = DataMap, is_instance = True)

    # -------------------------------------------------- Parameters with GUI Widgets --------------------------------------------------

    # -------------------------------------------------- Constructor --------------------------------------------------
    def __init__(self, **params):
        """
        Creates a new instance of the Application class with its instance variables.
        """
        super().__init__(**params)