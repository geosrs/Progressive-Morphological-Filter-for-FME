"""
Requires scipy to be installed

This code is to be pasted into an FME PythonCaller which receives a raster as
input. Currently supported band interpretations include Real64 and Real32. Other
formats can be added.

The code first unpacks the fme raster object and loads it into a numpy array.
On this array it performs an erosion with a kernel function that determins a cutoff
value for z-difference depending on distance between two points. This method is
discussed by Vosselman, G. (2000) "Slope based filtering of Laser Altimetry data"
It filters the input raster, retaining points within the desired cutoff.

The output is again an FME raster object
"""

import fmeobjects
import numpy as np
from scipy import ndimage

# Raster reading and writing functions based on code from Takashi: https://knowledge.safe.com/questions/38000/python-fme-objects-api-for-raster-manipulation.html

class RasterReader():
    def __init__(self):
        pass

    def tileAndInterpretation(self, interpretation, numRows, numCols):
        if interpretation == fmeobjects.FME_INTERPRETATION_REAL64:
            return (fmeobjects.FMEReal64Tile(numRows, numCols), 'REAL64')
        elif interpretation == fmeobjects.FME_INTERPRETATION_REAL32:
            return (fmeobjects.FMEReal32Tile(numRows, numCols), 'REAL32')
        ######################################################
        # Add other interpretations here if necessary.
        ######################################################
        else:
            return (None, 'Unsupported')

    # Returns a dictionary containing the statistics of specified band.
    def retrieveTiles(self, band, numRows, numCols):
        # Get the band properties.
        bandProperties = band.getProperties()
        interpretation = bandProperties.getInterpretation()

        # Create a tile that will be used to get cell values of the band.
        # The interpretation, number of rows, and number of columns
        # have to be consistent with the band properties.
        tile, interpret = self.tileAndInterpretation(interpretation,
            numRows, numCols)

        if tile != None:
            # Get all the cell values except Nodata as a list.
            values = []
            for data in band.getTile(0, 0, tile).getData():
                values += data

        return values

###############################################################################

class MyTilePopulator(fmeobjects.FMEBandTilePopulator):
    def __init__(self, dataArray):
        self.dataArray = dataArray

    # Implement 'clone' method.
    # It will be called multiple times while creating a new band.
    def clone(self):
        return MyTilePopulator(self.dataArray)

    # Implement 'getTile' method.
    # You can create a new tile containing desired contents here.
    # It's not essential to use the parameters: startRow, startCol, tile.
    def getTile(self, startRow, startCol, tile):
        numRows, numCols = len(self.dataArray), len(self.dataArray[0])
        newTile = fmeobjects.FMEReal64Tile(numRows, numCols)                      # <------------
        newTile.setData(self.dataArray)
        return newTile

    # The following two methods won't be called while creating a new band.
    # It seems not to be essential to implement these methods in this case,
    # although the API doc says "This method must be implemented
    # in the FMEBandTilePopulator subclass".
    def setDeleteSourceOnDestroy(self, deleteFlag):
        pass
    def setOutputSize(self, rows, cols):
        return (rows, cols)

###############################################################################

class ErosionKernel(object):
    def __init__(self):
        # Specify main parameters:
        #Slope tolerance delta H max - tolerated increase in H for distance between two points
        self.dhmax = 0.3
        #Grid size
        self.a = 0.5
        #Kernel Size
        k = int(FME_MacroValues['Kernel_Size'])
        self.kernel = (k,k) #only uneven numbers!
    # Returns a tuple (tile object, interpretation name).
    # This method returns (None, 'Unsupported')
    # when the specified interpretation was not supported,


    ###########################################################################
    #My code
    def maxSlopeErosion(self, input, kernel, dhmax):
        def setupStructureElement(kernel, dhmax):
            #Throw error if kernel set wrong
            if kernel[0]%2 == 0 or kernel[1]%2 == 0:
                raise ValueError("The kernel shape cannot contain even numbers!")

            structure_element = np.zeros(kernel) #same size
            for i in range(kernel[0]):
                for j in range(kernel[1]):
                    centerx = (kernel[1]-1)/2
                    centery = (kernel[0]-1)/2
                    dx = self.a * (j - centerx)
                    dy = self.a * (i - centery)
                    value = -dhmax * np.sqrt(dx**2+dy**2) #following Vosselman(2000)
                    structure_element[i,j] = value

            return structure_element

        s = setupStructureElement(kernel, dhmax)

        output = ndimage.morphology.grey_erosion(input, structure = s)
        return output

    def maxSlopeFilter(self, input_raster, kernel, dhmax):
        #Replace -9999 with NaN
        input_raster[input_raster==-9999]=9999

        #Call Erosion
        eroded = self.maxSlopeErosion(input_raster, kernel, dhmax)

        #Only return those below cutoff
        output = np.where(input_raster <= eroded, input_raster, np.nan)
        #Reintroduce nan
        output[output==9999]=np.nan
        return output

    ###########################################################################

    def input(self, feature):
        raster = feature.getGeometry()
        if isinstance(raster, fmeobjects.FMERaster):
            self.rasterProperties = raster.getProperties()

            MyRasterReader = RasterReader()
            #for band 0
            tiles = MyRasterReader.retrieveTiles(raster.getBand(0), self.rasterProperties.getNumRows(), self.rasterProperties.getNumCols())
            tiles_matrix = np.array([tiles])
            tiles_matrix = tiles_matrix.reshape(self.rasterProperties.getNumRows(), self.rasterProperties.getNumCols()) #From this point on i have my raster


            # Output Raster
            self.filtered = self.maxSlopeFilter(tiles_matrix, self.kernel, self.dhmax)

        return

    ###########################################################################
    def close(self):
        # Contents of a tile for a band to be created.
        # A list of row data, each element is a list of column values.
        print("Converting to raster.")
        # Taking over our input raster's properties
        raster = fmeobjects.FMERaster(self.rasterProperties)

        #Clean the output array
        dataArray = self.filtered.astype(float)
        dataArray[np.isnan(dataArray)]=-9999.0
        dataArray = dataArray.tolist()



        bandTilePopulator = MyTilePopulator(dataArray)                 # <------------ changed class name

        bandName = "Slope Erosion Filtered"
        bandProperties = fmeobjects.FMEBandProperties(bandName,
            fmeobjects.FME_INTERPRETATION_REAL64,                         # <----------- changed from UInt8
            fmeobjects.FME_TILE_TYPE_FIXED,
            self.rasterProperties.getNumRows(), self.rasterProperties.getNumCols())
        nodataValue = fmeobjects.FMEReal64Tile(1, 1)                      # <----------- changed from UInt8
        nodataValue.setData([[-9999.0]])
        band = fmeobjects.FMEBand(bandTilePopulator,
            self.rasterProperties, bandProperties, nodataValue)
        raster.appendBand(band)

        # Create and output a feature containing the raster created above.
        feature = fmeobjects.FMEFeature()
        feature.setGeometry(raster)
        print("Saving raster output.")
        self.pyoutput(feature)