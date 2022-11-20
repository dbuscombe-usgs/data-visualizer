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
from bokeh.palettes import Bokeh

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
        # _timeseries_plot = timeseries plot for the most recently clicked transect (path)
        self._time_series_plot = gv.DynamicMap(self._create_time_series, streams = list(self._tapped_data_streams.values()))
        # _clicked_transect_pipe = pipe stream that sends data about the most recently clicked transect
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
        total_palette_colors = len(palette_colors)
        markers = ["o", "^", "s", "d", "x", ">", "*", "v", "+", "<"]
        total_markers = len(markers)
        for i, category in enumerate(self._all_categories):
            # Assign the color that the user chose, if provided.
            if category in colors:
                self._category_colors[category] = colors[category]
            # Else assign a color from the Bokeh palette.
            else:
                self._category_colors[category] = palette_colors[i % total_palette_colors]
            # Assign a marker.
            self._category_markers[category] = markers[i % total_markers]
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
            # # Convert the data file into a GeoViews Dataset.
            # dataframe = pd.read_csv(file_path)
            # non_lat_long_cols, latitude_col, longitude_col = [], None, None
            # for col in dataframe.columns:
            #     if col in self._all_lat_cols: latitude_col = col
            #     elif col in self._all_long_cols: longitude_col = col
            #     else: non_lat_long_cols.append(col)
            # data = gv.Dataset(
            #     dataframe,
            #     kdims = non_lat_long_cols
            # )
            # # Create a point plot with the GeoViews Dataset.
            # plot = data.to(
            #     gv.Points,
            #     kdims = [longitude_col, latitude_col],
            #     vdims = non_lat_long_cols,
            #     label = category
            # ).opts(
            #     opts.Points(
            #         color = self._category_colors[category],
            #         marker = self._category_markers[category],
            #         tools = ["hover"],
            #         size = 10, muted_alpha = 0.01
            #     )
            # )
            # Convert the data file into a new GeoJSON (if not created yet).
            geojson_path = category_geodata_dir_path + "/" + name + ".geojson"
            if not os.path.exists(geojson_path):
                # Create the GeoData folder if it doesn't exist yet.
                if not os.path.isdir(category_geodata_dir_path): os.makedirs(category_geodata_dir_path)
                # Create a FeatureCollection of Points based on the data file.
                self._create_data_points_geojson(file_path, geojson_path)
            # Create a point plot with the GeoJSON.
            plot = self._plot_geojson_points(geojson_path, category)
        # elif extension == ".geojson":
        #     # Directly read from the data file if a GeoJSON was given.
        #     plot = self._plot_geojson_points(file_path, category)
        elif extension == ".asc":
            geotiff_path = category_geodata_dir_path + "/" + name + ".tif"
            # Convert ASCII grid file into a new GeoTIFF (if not created yet).
            if not os.path.exists(geotiff_path):
                dataset = rxr.open_rasterio(file_path)
                # Add custom projection based on the Elwha data's metadata.
                dataset.rio.write_crs(self._crs, inplace = True)
                # Create the GeoData folder if it doesn't exist yet.
                if not os.path.isdir(category_geodata_dir_path): os.makedirs(category_geodata_dir_path)
                # Save the data as a GeoTIFF.
                dataset.rio.to_raster(
                    raster_path = geotiff_path,
                    driver = "GTiff"
                )
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
        # elif extension == ".geojson":
        #     plot = self._plot_geojson_linestrings(file_path, filename)
        # Save the path plot, if created.
        if plot is None:
            print("Error displaying", name + extension, "as a path plot:", "Input files with the", extension, "file format are not supported yet.")
        else:
            self._created_plots[filename] = plot
    
    def _create_time_series(self, **params: dict) -> gv.Points:
        """
        Creates a time-series plot for data collected along a clicked transect on the map.

        Args:
            params (dict): Dictionary mapping each transect filename (keys) to a list containing the indices of selected/clicked/tapped transects (values) from its transect file
        """
        plot = gv.Points([])
        # print("Selection1D streams' parameters:", params)
        for file in self._all_transect_files:
            clicked_transect_indices = params[file]
            num_clicked_transects = len(clicked_transect_indices)
            if num_clicked_transects == 1:
                # Open the app's modal to display the time-series plot.
                self._app_template.open_modal()
                # Get the user's clicked transect.
                [transect_index] = clicked_transect_indices
                transects_file_plot = self._created_plots[file]
                transect_file_paths = transects_file_plot.split()
                clicked_transect_data = transect_file_paths[transect_index].columns(dimensions = ["Longitude", "Latitude", "Transect ID"])
                # Rename GeoViews' default coordinate column names.
                new_clicked_transect_data = {}
                for col, values in clicked_transect_data.items():
                    if col == "Longitude": col = "Easting (meters)"
                    elif col == "Latitude": col = "Northing (meters)"
                    new_clicked_transect_data[col] = values.tolist()
                # Add a new "Point Type" column to differentiate the transect points.
                new_clicked_transect_data[self._point_type_col_name] = ["start", "end"]
                # Update the transect pipe stream's data parameter and trigger an event in order to update the transect's data table.
                self._clicked_transect_pipe.event(data = new_clicked_transect_data)
                # Get data collected along the transect.
                data = gv.Points([])
                # Create time-series plot for all data collected along the clicked transect.
                plot = data.opts(
                    title = "Time-Series of Data Collected Along the Selected Transect"
                )
            elif num_clicked_transects > 1:
                print("Error creating time-series of data: Only 1 transect should be selected but {} were selected.".format(num_clicked_transects))
            # Reset transect file's Selection1D stream parameter to its default value (empty list []).
            self._tapped_data_streams[file].reset()
        return plot

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
            editable = False
        )

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
    def time_series_plot(self) -> gv.DynamicMap:
        """
        Returns a time-series plot for data collected near the selected transect on the map.
        """
        return self._time_series_plot

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