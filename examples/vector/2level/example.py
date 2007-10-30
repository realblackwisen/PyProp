#import system modules
import sys
import os

#pytables
import tables

#numerical modules
from numpy import *
import pylab

#home grown modules
pyprop_path = "../../../"
sys.path.insert(1, os.path.abspath(pyprop_path))
import pyprop
pyprop = reload(pyprop)

c = 0.1
d = 0.005
e = 0.15

def GetMatrix():
	return array([[0, c, d], [c, 0, e], [d,e,0]], dtype=complex)

def GetDiagonalElements():
	data = pylab.load('energies.dat')
	return array(data, dtype=complex)

def Propagate():
	conf = pyprop.Load("config.ini")
	prop = pyprop.Problem(conf)
	prop.SetupStep()

	init = prop.psi.Copy()
	corr = []
	times = []
	corr.append(abs(prop.psi.GetData()[:])**2)
	times += [0]
	for t in prop.Advance(400):
		#corr += [abs(prop.psi.InnerProduct(init))**2]
		corr.append(abs(prop.psi.GetData()[:])**2)
		times += [t]
		print "Time = ", t, ", initial state correlation = ", corr[-1][0]

	#pylab.plot(times, corr)

	return times, array(corr)


#class SparseMatrix(tables.IsDescription):
#	RowIndex = tables.Int32Col(pos=1)
#	ColIndex = tables.Int32Col(pos=2)
#	MatrixElement = tables.ComplexCol(itemsize=16, pos=3)

#def CreateHDF5FileFromText(fileName,vectorSize):
#	RowIndex = tables.Int32Col(pos=1)
#	ColIndex = tables.Int32Col(pos=2)
#	MatrixElement = tables.ComplexCol(itemsize=16, pos=3)
#
#	data = pylab.load(fileName)
#
#	fileh5 = tables.openFile(fileName + '.h5', 'w')
#	# Create a new group
#	group = fileh.createGroup(fileh.root, "doubledot")
#
#	# Create a new table in group groupName
#	tableName = "matrixElements"
#	tableTitle = "Double quantum dot matrix elements"
#	table = fileh.createTable(group, tableName, SparseMatrix, tableTitle, Filters(1))
#	sparseMatrixRow = table.row
#
## Fill the table with 10 particles
#for i in xrange(10):
#    # First, assign the values to the Particle record
#    particle['name']  = 'Particle: %6d' % (i)
#    particle['lati'] = i
#    particle['longi'] = 10 - i
#    particle['pressure'] = float(i*i)
#    particle['temperature'] = float(i**2)
#    # This injects the row values.
#    particle.append()


def TextToHDFDense(fileName, vectorSize):

	groupName = 'doubledot'
	datasetPath = '/' + groupName + '/matrixelements'
	data = pylab.load(fileName)

	fileh5 = tables.openFile(fileName + '.h5', 'w')
	
	try:
		group = fileh5.createGroup(fileh5.root, groupName)
		h5array = pyprop.serialization.CreateDataset(fileh5, datasetPath, (vectorSize,vectorSize))

		#Fill h5array with matrix element data
		for i in range(shape(data)[0]):
			row = int(data[i,0]) - 1
			col = int(data[i,1]) - 1
			matel = data[i,2]
			h5array[row, col] = matel 
			h5array[col,row] = matel

	finally:
		fileh5.close()



