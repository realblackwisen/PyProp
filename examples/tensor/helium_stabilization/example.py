import sys
import os
import time
try:
	import pysparse
	import scipy.linalg
except:
	pass

from datetime import timedelta

sys.path.append("./pyprop")
import pyprop
pyprop = reload(pyprop)
pyprop.ProjectNamespace = globals()

from numpy import *
#from pylab import *
from libpotential import *
from pyprop import PrintOut

execfile("stabilization.py")
execfile("twoelectron_test.py")
execfile("benchmark.py")
execfile("eigenvalues.py")

try:
	import scipy
	import scipy.sparse
	import scipy.linsolve
	scipy.linsolve.use_solver(useUmfpack=False)
except:
	pyprop.PrintOut("Could not load scipy")

INSTALLATION = os.environ.get("INSTALLATION", "local")
if INSTALLATION == "hexagon":
	import pyprop.utilities.submitpbs_hexagon as submitpbs
elif INSTALLATION == "stallo":
	import pyprop.utilities.submitpbs_stallo as submitpbs

#------------------------------------------------------------------------------------
#                       Setup Functions
#------------------------------------------------------------------------------------


def SetupConfig(**args):
	configFile = args.get("config", "config.ini")
	conf = pyprop.Load(configFile)
	
	if "silent" in args:
		silent = args["silent"]
		conf.Propagation.silent = silent

	if "lmax" in args or "L" in args:
		lmax = args["lmax"]
		L = args["L"]
		indexIterator = pyprop.DefaultCoupledIndexIterator(lmax=lmax, L=L)
		conf.SetValue("AngularRepresentation", "index_iterator", indexIterator)

	if "imtime" in args:
		imtime = args["imtime"]
		if imtime:
			conf.SetValue("Propagation", "timestep", 1.0j * abs(conf.Propagation.timestep))
			conf.SetValue("Propagation", "renormalization", True)
		else:
			conf.SetValue("Propagation", "timestep", abs(conf.Propagation.timestep))
			conf.SetValue("Propagation", "renormalization", False)

	if "duration" in args:
		duration = args["duration"]
		conf.SetValue("Propagation", "duration", duration)

	if "eigenvalueCount" in args:
		conf.SetValue("Arpack", "krylov_eigenvalue_count", args["eigenvalueCount"])

	if "eigenvalueBasisSize" in args:
		conf.SetValue("Arpack", "krylov_basis_size", args["eigenvalueBasisSize"])

	if "eigenvalueShift" in args:
		conf.SetValue("GMRES", "shift", args["eigenvalueShift"])
		print "Using shift ", args["eigenvalueShift"]

	if "shift" in args:
		conf.SetValue("GMRES", "shift", args["shift"])
		print "Using shift ", args["shift"]

	if "index_iterator" in args:
		conf.SetValue("AngularRepresentation", "index_iterator", args["index_iterator"])

	if "amplitude" in args:
		conf.SetValue("PulseParameters", "amplitude", args["amplitude"])

	if args.get("useDefaultPotentials", True):
		potentials = conf.Propagation.grid_potential_list 
	else:
		potentials = []
	potentials += args.get("additionalPotentials", [])
	conf.SetValue("Propagation", "grid_potential_list", potentials)

	#Update config object from possible changed ConfigParser object
	newConf = pyprop.Config(conf.cfgObj)

	return newConf


def SetupProblem(**args):
	conf = SetupConfig(**args)
	prop = pyprop.Problem(conf)
	prop.SetupStep()

	return prop


def FindGroundstate(**args):
	prop = SetupProblem(imtime=True, **args)
	for t in prop.Advance(True):
		E = prop.GetEnergy()
		if pyprop.ProcId == 0:
			print "t = %02.2f, E = %2.8f" % (t, E)

	E = prop.GetEnergyExpectationValue()
	print "t = %02.2f, E = %2.8f" % (t, E)

	return prop


def FindEigenvalues(useArpack = False, **args):
	prop = SetupProblem(**args)
	if useArpack:
		solver = pyprop.ArpackSolver(prop)
	else:
		solver = pyprop.PiramSolver(prop)
	solver.Solve()
	print solver.GetEigenvalues()
	return solver


def SetupPotentialMatrix(prop, whichPotentials):
	print "Setting up potential matrix..."
	matrixSize = prop.psi.GetData().size
	
	#Allocate the potential matrix
	print "    Allocating potential matrix of size [%i, %i]  ~%.0f MB" \
		% (matrixSize, matrixSize, matrixSize**2 * 16 / 1024.**2)
	BigMatrix = zeros((matrixSize, matrixSize), dtype="complex")

	for potNum in whichPotentials:
		potential = prop.Propagator.BasePropagator.PotentialList[potNum]
		print "    Processing potential %i: %s" % (potNum, potential.Name)

		for idxL, idxR, i, j, k in TensorPotentialIndexMap(prop.psi.GetData().shape, potential):
			BigMatrix[idxL, idxR] += potential.PotentialData[i, j, k]

	return BigMatrix


def SetupPotentialMatrixLL(prop, whichPotentials, eps=1e-14):
	def SetElement():
		MatrixLL[idxL, idxR] += potential.PotentialData[i, j, k].real

	print "Setting up potential matrix..."
	matrixSize = prop.psi.GetData().size

	#Find potential size for largest potential
	potList = prop.Propagator.BasePropagator.PotentialList
	potentialSize = max([potList[w].PotentialData.size for w in whichPotentials])

	#Set up linked list matrix
	MatrixLL = pysparse.spmatrix.ll_mat_sym(matrixSize, potentialSize)
	#MatrixLL = pysparse.spmatrix.ll_mat(matrixSize, matrixSize)

	countSize = 1e4

	for potNum in whichPotentials:
		potential = prop.Propagator.BasePropagator.PotentialList[potNum]
		print "    Processing potential %i: %s" % (potNum, potential.Name)
		curPotSize = potList[potNum].PotentialData.size

		count = 0
		outStr = ""
		for idxL, idxR, i, j, k in TensorPotentialIndexMap(prop.psi.GetData().shape, potential):
			#Skip upper triangle (we have a symmetric matrix)
			if idxL < idxR:
				continue

			#Skip current element if less than eps
			if abs(potential.PotentialData[i, j, k]) < eps:
				continue

			#Print progress info
			if mod(count, countSize) == 0:
				outStr = " " * 8
				outStr += "Progress: %i/%i" % (count/countSize, round(curPotSize/2./countSize))
				#outStr += "Progress: %i/%i" % (count/countSize, round(curPotSize/countSize))
				sys.stdout.write("\b"*len(outStr) + outStr)
				sys.stdout.flush()

			#Store element in linked-list matrix
			#MatrixLL[idxL, idxR] += potential.PotentialData[i, j, k].real
			SetElement()
			count += 1

		print


	return MatrixLL


def TensorPotentialIndexMap(psiShape, tensorPotential):
	"""
	Returns a generator for a map between indices in an m x m matrix and 
	"""
	basisPairs0 = tensorPotential.BasisPairs[0]
	basisPairs1 = tensorPotential.BasisPairs[1]
	basisPairs2 = tensorPotential.BasisPairs[2]

	basisCount0 = basisPairs0.shape[0]
	basisCount1 = basisPairs1.shape[0]
	basisCount2 = basisPairs2.shape[0]
	
	Count0 = psiShape[0]
	Count1 = psiShape[1]
	Count2 = psiShape[2]

#	for i, (x0,x0p) in enumerate(basisPairs0):
#		xIndex0 = (x0 * Count1 * Count2)
#		xIndex0p = (x0p * Count1 * Count2) 
#		for j, (x1,x1p) in enumerate(basisPairs1):
#			xIndex1 = (x1 * Count2)
#			xIndex1p = (x1p * Count2)
#			for k, (x2,x2p) in enumerate(basisPairs2):
#				indexLeft = x2 + xIndex1 + xIndex0
#				indexRight = x2p + xIndex1p + xIndex0p 
#				yield indexLeft, indexRight, i, j, k
	for i in xrange(basisCount0):
		xIndex0 = (basisPairs0[i,0] * Count1 * Count2)
		xIndex0p = (basisPairs0[i,1] * Count1 * Count2) 
		for j in xrange(basisCount1):
			xIndex1 = (basisPairs1[j,0] * Count2)
			xIndex1p = (basisPairs1[j,1] * Count2)
			for k in xrange(basisCount2):
				indexLeft = basisPairs2[k,0] + xIndex1 + xIndex0
				indexRight = basisPairs2[k,1] + xIndex1p + xIndex0p 
				yield indexLeft, indexRight, i, j, k



def TensorPotentialIndexMapOld(psiShape, tensorPotential):
	"""
	Returns a generator for a map between indices in an m x m matrix and 
	"""
	basisPairs0 = tensorPotential.BasisPairs[0]
	basisPairs1 = tensorPotential.BasisPairs[1]
	basisPairs2 = tensorPotential.BasisPairs[2]
	
	Count0 = psiShape[0]
	Count1 = psiShape[1]
	Count2 = psiShape[2]

	for i, (x0,x0p) in enumerate(basisPairs0):
		for j, (x1,x1p) in enumerate(basisPairs1):
			for k, (x2,x2p) in enumerate(basisPairs2):
				indexLeft = x2 + (x1 * Count2) + (x0 * Count1 * Count2) 
				indexRight = x2p + (x1p * Count2) + (x0p * Count1 * Count2) 
				yield indexLeft, indexRight, i, j, k


def SetupBigMatrixReal(prop, whichPotentials):
	print "Setting up potential matrix..."
	matrixSize = prop.psi.GetData().size
	psiShape = prop.psi.GetData().shape
	
	#Allocate the hamilton matrix
	print "    Allocating potential matrix of size [%i, %i]  ~%.0f MB" \
		% (matrixSize, matrixSize, matrixSize**2 * 8 / 1024.**2)
	BigMatrix = zeros((matrixSize, matrixSize), dtype="double")

	for potNum in whichPotentials:
		potential = prop.Propagator.BasePropagator.PotentialList[potNum]
		print "    Processing potential %i: %s" % (potNum, potential.Name)

		basisPairs0 = potential.BasisPairs[0]
		basisPairs1 = potential.BasisPairs[1]
		basisPairs2 = potential.BasisPairs[2]
		
		Count0 = prop.psi.GetData().shape[0]
		Count1 = prop.psi.GetData().shape[1]
		Count2 = prop.psi.GetData().shape[2]

		tMap = TensorPotentialIndexMap
		for idxL, idxR, i, j, k in tMap(psiShape, potential):
			BigMatrix[idxL, idxR] += potential.PotentialData[i, j, k].real

	return BigMatrix


#------------------------------------------------------------------------------------
#                       Laser Time Functions
#------------------------------------------------------------------------------------

def LaserFunctionVelocity(conf, t):
	if 0 <= t < conf.pulse_duration:
		curField = conf.amplitude;
		curField *= sin(t * pi / conf.pulse_duration)**2;
		curField *= - cos(t * conf.frequency);
	else:
		curField = 0
	return curField


def LaserFunctionSimpleLength(conf, t):
	if 0 <= t < conf.pulse_duration:
		curField = conf.amplitude;
		curField *= sin(t * pi / conf.pulse_duration)**2;
		curField *= cos(t * conf.frequency);
	else:
		curField = 0
	return curField


def LaserFunctionLength(conf, t):
	if 0 <= t < conf.pulse_duration:
		curField = conf.amplitude;
		T = conf.pulse_duration
		w = conf.frequency
		curField *= sin(pi*t/T)*(-2*pi/T * cos(pi*t/T) * cos(w*t) + w*sin(pi*t/T)*sin(w*t))
	else:
		curField = 0
	return curField


#------------------------------------------------------------------------------------
#                       Debug Functions
#------------------------------------------------------------------------------------

def GetBasisPairs(selectionRule, indexIterator):
	class reprConfigSection(pyprop.Section):
		def __init__(self):
			self.index_iterator = indexIterator

	cfg = reprConfigSection()
	repr = pyprop.core.CoupledSphericalHarmonicRepresentation()
	cfg.Apply(repr)

	return selectionRule.GetBasisPairs(repr)


#------------------------------------------------------------------------------------
#                       Job Submit Functions
#------------------------------------------------------------------------------------
installation = os.environ.get("INSTALLATION", "local")
if installation == "hexagon":
	import pyprop.utilities.submitpbs_hexagon as submitpbs
if installation == "stallo":
	import pyprop.utilities.submitpbs_stallo as submitpbs

import commands


def Submit(executable=None, writeScript=False, installation="hexagon", **args):
	"""
	Set up job scripts and other necessary stuff to run ionization rate
	cycle scan experiment.
	"""

	#Create jobscript 
	numProcs = args.get("numProcs", 1)

	jscript = submitpbs.SubmitScript()
	jscript.jobname = args.get("jobname", "pyprop")
	jscript.walltime = timedelta(hours=args.get("runHours",1), minutes=0, seconds=0)
	jscript.ppn = args.get("ppn", 4)
	jscript.proc_memory = args.get("proc_memory", "1000mb")
	jscript.nodes = int(ceil(numProcs / float(jscript.ppn)))
	jscript.interconnect = args.get("interconnect", "ib")
	if installation == "stallo":
		jscript.workingdir = args.get("workingDir", "/home/nepstad/proj/argon/")
		jscript.executable = "mpirun -n %s " % (jscript.ppn*jscript.nodes)
		jscript.executable += "python %s" % executable
	elif installation == "hexagon":
		jscript.workingdir = args.get("workingDir")
		jscript.executable = "aprun -n %s " % numProcs
		jscript.executable += "./python-exec %s" % executable
	jscript.parameters = commands.mkarg(repr(args))
	jscript.account = args.get("account", "fysisk")

	#Submit this job
	if writeScript:
		print "\n".join(jscript.CreateScript())
	else:
		jscript.Submit()


#------------------------------------------------------------------------------------
#                       Serialization Functions
#------------------------------------------------------------------------------------
def SetupProblemFromFile(file, nodeName=None):
	"""
	Set up problem object and load wavefunction from file.
	"""
	prop = None
	cfgObj = pyprop.serialization.GetConfigFromHDF5(file)
	cfgObj.set("InitialCondition", "type", "None")
	conf = pyprop.Config(cfgObj)
	prop = pyprop.Problem(conf)
	prop.SetupStep()

	GetWavefunctionFromFile(file, prop.psi, nodeName=nodeName)
	
	return prop


def GetWavefunctionFromFile(file, psi, nodeName=None):
	h5file = tables.openFile(file, "r")
	try:
		if nodeName == None:
			for node in h5file.walkNodes():
				if node._v_name == "wavefunction":
					psi.GetData()[:] = node[:]
		else:
			psi.GetData()[:] = h5file.getNode(nodeName)[:]
	finally:
		h5file.close()


def GetArrayFromFile(file, nodeName):
	h5file = tables.openFile(file, "r")
	try:
		for node in h5file.walkNodes():
			if node._v_name == nodeName:
				dataArray = node[:]
	finally:
		h5file.close()
	
	return dataArray


def StoreTensorPotentialMTX(prop, whichPotentials, outFileName, eps = 1e-14):
	fh = open(outFileName, "w")
	for potNum in whichPotentials:
		potential = prop.Propagator.BasePropagator.PotentialList[potNum]
		print "    Processing potential %i: %s" % (potNum, potential.Name)

		basisPairs0 = potential.BasisPairs[0]
		basisPairs1 = potential.BasisPairs[1]
		basisPairs2 = potential.BasisPairs[2]
		
		Count0 = prop.psi.GetData().shape[0]
		Count1 = prop.psi.GetData().shape[1]
		Count2 = prop.psi.GetData().shape[2]

		for i, (x0,x0p) in enumerate(basisPairs0):
			for j, (x1,x1p) in enumerate(basisPairs1):
				for k, (x2,x2p) in enumerate(basisPairs2):
					indexLeft = x2 + (x1 * Count2) + (x0 * Count1 * Count2) 
					indexRight = x2p + (x1p * Count2) + (x0p * Count1 * Count2) 

					#Skip current element if less than eps
					if abs(potential.PotentialData[i, j, k]) < eps:
						continue

					#Write data line to file
					potReal = potential.PotentialData[i, j, k].real
					potImag = potential.PotentialData[i, j, k].imag
					outStr = "%i %i %1.16f %1.16f\n" % (indexLeft, indexRight, potReal, potImag)
					fh.write(outStr)

	fh.close()




#------------------------------------------------------------------------------------
#                       Eigenvalue Functions
#------------------------------------------------------------------------------------

def FindEigenvaluesJD(howMany, shift, tol = 1e-10, maxIter = 200, dataSetPath="/", \
	configFileName="config_eigenvalues.ini", L=0, lmax=4, outFileName = "eig_jd.h5", \
	preconType = None):
	"""
	Find some eigenvalues for a given L-subspace using Jacobi-Davidson method
	"""

	#Set up problem
	idxIt = pyprop.DefaultCoupledIndexIterator(lmax = lmax, L = L)
	prop = SetupProblem(config = configFileName, index_iterator = idxIt)

	#Set up hamilton matrix
	H_ll = SetupPotentialMatrixLL(prop,[0,1])
	H = H_ll.to_sss()

	#Set up overlap matrix
	S_ll = SetupPotentialMatrixLL(prop,[2])
	S = S_ll.to_sss()

	#Set up preconditioner
	Precon = None
	if preconType:
		Precon = preconType(H_ll)

	#Call Jacobi-Davison rountine
	numConv, E, V, numIter, numIterInner = \
		pysparse.jdsym.jdsym(H, S, Precon, howMany, shift, tol, maxIter, pysparse.itsolvers.qmrs)

	#Store eigenvalues and eigenvectors
	h5file = tables.openFile(outFileName, "w")
	try:
		myGroup = h5file.createGroup("/", "Eig")
		h5file.createArray(myGroup, "Eigenvectors", V)
		h5file.createArray(myGroup, "Eigenvalues", E)
		myGroup._v_attrs.NumberOfIterations = numIter
		myGroup._v_attrs.NumberOfInnerIterations = numIterInner
		myGroup._v_attrs.NumberOfConvergedEigs = numConv
		myGroup._v_attrs.configObject = prop.Config.cfgObj
	finally:
		h5file.close()


	return numConv, E, V, numIter, numIterInner


def FindEigenvaluesDirectDiagonalization(L=0, lmax=3, storeResult=False, checkSymmetry=False, \
	outFileName = "eig_direct.h5"):
	"""
	Get energies and eigenstates by direct diagonalization of L-subspace matrix
	"""
	#Coupled spherical index iterator based on given lmax and L
	index_iterator = pyprop.DefaultCoupledIndexIterator(lmax=lmax, L=L)
	
	#Set up problem
	prop = SetupProblem(config="config_eigenvalues.ini", index_iterator=index_iterator)

	#Set up hamilton and overlap matrices
	HamiltonMatrix = SetupBigMatrixReal(prop, [0,1])
	OverlapMatrix = SetupBigMatrixReal(prop, [2])

	#Calculate generalized eigenvalues and eigenvectors
	print "Calculating generalized eigenvalues and eigenvectors..."
	sys.stdout.flush()
	E, V = scipy.linalg.eig(HamiltonMatrix, b=OverlapMatrix)

	#Sort eigenvalues and eigenvectors
	sortIdx = argsort(E)
	E = E[sortIdx].real
	V = V[:,sortIdx]

	#Check symmetry of eigenstates
	print "Checking symmetry of eigenstates..."
	psiShape = prop.psi.GetData().shape
	lmax = psiShape[0]
	eps = 1e-9
	symmetryList = []
	if checkSymmetry:
		for stateIdx in range(len(E)):
			
			#Check symmetry of l-component with largest norm
			lSpaceNorm = \
				[scipy.linalg.norm(V[:,stateIdx].reshape(psiShape)[i,:]) for i in range(lmax)]
			largestComponentIdx = argmax(lSpaceNorm)
			v_radial = V[:,stateIdx].reshape(psiShape)[largestComponentIdx,:,:]

			#Check if even/odd or not symmetric
			if scipy.linalg.norm(v_radial - transpose(v_radial)) < eps:
				symmetryList.append("Even")
			elif scipy.linalg.norm(v_radial + transpose(v_radial)) < eps:
				symmetryList.append("Odd")
			else:
				print "E = %s, idx = %s" % (E[stateIdx], stateIdx)
				symmetryList.append("NoSym")

	#Store result
	if storeResult:
		h5file = tables.openFile(outFileName, "w")
		try:
			myGroup = h5file.createGroup("/", "Eig")
			h5file.createArray(myGroup, "Eigenvectors", V)
			h5file.createArray(myGroup, "Eigenvalues", E)
			if symmetryList:
				h5file.createArray(myGroup, "SymmetryList", symmetryList)
			myGroup._v_attrs.configObject = prop.Config.cfgObj
		finally:
			h5file.close()

	#...or return result
	else:
		return prop, HamiltonMatrix, OverlapMatrix, E, V


def FindEigenvaluesInverseIterations(config="config_eigenvalues.ini", \
	outFileName="out/eig_inverseit.h5", **args):
			
	prop = SetupProblem(silent = True, config=config, **args)

	#Setup shift invert solver in order to perform inverse iterations
	shiftInvertSolver = pyprop.GMRESShiftInvertSolver(prop)
	prop.Config.Arpack.matrix_vector_func = shiftInvertSolver.InverseIterations
	shift = prop.Config.GMRES.shift

	#Setup eiganvalue solver & solve
	solver = pyprop.PiramSolver(prop)
	solver.Solve()

	#Print statistics from superLU
	for solve in shiftInvertSolver.Preconditioner.RadialSolvers:
		solve.PrintStatistics()

	#Get error estimates from GMRES
	errorEstimatesGMRES = shiftInvertSolver.Solver.GetErrorEstimateList()

	#Get eigenvalue error estimate
	errorEstimatesPIRAM = solver.Solver.GetErrorEstimates()
	convergenceEstimatesEig = solver.Solver.GetConvergenceEstimates()

	#Get eigenvalues
	E = 1.0 / array(solver.GetEigenvalues()) + shift

	#Store eigenvalues and eigenvectors
	PrintOut("Now storing eigenvectors...")
	for i in range(len(E)):
		solver.SetEigenvector(prop.psi, i)
		prop.SaveWavefunctionHDF(outFileName, "/Eig/Eigenvector%03i" % i)

	if pyprop.ProcId == 0:
		h5file = tables.openFile(outFileName, "r+")
		try:
			#myGroup = h5file.createGroup("/", "Eig")
			myGroup = h5file.getNode("/Eig")
			h5file.createArray(myGroup, "Eigenvalues", E)
			h5file.createArray(myGroup, "ErrorEstimateListGMRES", errorEstimatesGMRES)
			h5file.createArray(myGroup, "ErrorEstimateListPIRAM", errorEstimatesPIRAM)
			h5file.createArray(myGroup, "ConvergenceEstimateEig", convergenceEstimatesEig)

			#Store config
			myGroup._v_attrs.configObject = prop.Config.cfgObj
			
			#PIRAM stats
			myGroup._v_attrs.opCount = solver.Solver.GetOperatorCount()
			myGroup._v_attrs.restartCount = solver.Solver.GetRestartCount()
			myGroup._v_attrs.orthCount = solver.Solver.GetOrthogonalizationCount()
		finally:
			h5file.close()

	return solver, shiftInvertSolver


class BlockPreconditioner:
	def __init__(self, A, blockSize=1):
		self.Matrix = A
		self.shape = A.shape
		self.BlockSize = blockSize
		self.ProbSize = A.shape[0]
		self.NumCalls = 0
		
		#Check that blocksize divides matrix shape
		if mod(self.ProbSize, self.BlockSize) != 0:
			raise Exception("Preconditioner block size must divide matrix size!")

		#Set up preconditioner matrix
		self.Preconditioner = pysparse.spmatrix.ll_mat(self.shape[0], self.shape[1])
		curBlock = zeros((self.BlockSize, self.BlockSize))
		for k in range(self.ProbSize / self.BlockSize):
			curBlock[:] = 0.0
			curSlice = [slice(k*(blockSize), (k+1)*blockSize)] * 2
			
			for i in range(self.BlockSize):
				for j in range(self.BlockSize):
					I = k * blockSize + i
					J = k * blockSize + j
					curBlock[i,j] = self.Matrix[I, J]

			invBlock = linalg.inv(curBlock)

			for i in range(self.BlockSize):
				for j in range(self.BlockSize):
					I = k * blockSize + i
					J = k * blockSize + j
					self.Preconditioner[I,J] = invBlock[i,j]

	def precon(self, x, y):
		self.Preconditioner.matvec(x, y)
		self.NumCalls += 1


#------------------------------------------------------------------------------------
#                      Misc Functions
#------------------------------------------------------------------------------------
def CalculatePolarizabilityGroundState(fieldRange = linspace(0.001,0.01,10), **args):
	"""
	Calculate polarizability of ground state using the Jacobi-Davidson method. We use
	the formula

	    polarizability = -2 * E_shift / field**2,
	
	thus assuming that the hyperpolarizability term is negligible.
	"""
	def JacobiDavidson(TotalMatrix):
		numConv, E, V, numIter, numIterInner = pysparse.jdsym.jdsym( \
			TotalMatrix, OverlapMatrix, None, 1, -3.0, 1e-10, 100, \
			pysparse.itsolvers.qmrs) 

		return E

	def SetupTotalMatrix(fieldStrength):
		#Add H matrix
		idx = H.keys()
		for key in idx:
			I = key[0]
			J = key[1]
			TotalMatrixLL[I,J] = H[I,J]

		#Add field matrix
		idx2 = FieldMatrix.keys()
		for key in idx2:
			I = key[0]
			J = key[1]
			TotalMatrixLL[I,J] = fieldStrength * FieldMatrix[I,J]

		TotalMatrix = TotalMatrixLL.to_sss()
		return TotalMatrix

	#Setup problem
	prop = SetupProblem(**args)

	#Set up the field-free hamilton matrix
	H = SetupPotentialMatrixLL(prop, [0,1])

	#Set up the field matrix
	FieldMatrix = SetupPotentialMatrixLL(prop, [2])

	#Set up overlap matrix
	S_ll = SetupPotentialMatrixLL(prop,[3])
	OverlapMatrix = S_ll.to_sss()

	#Setup total system matrix
	TotalMatrixLL = H.copy()

	#Get reference energy
	TotalMatrix = SetupTotalMatrix(0.0)
	refEnergy = JacobiDavidson(TotalMatrix)
	print "Reference energy = %.15f" % refEnergy

	#Store shifted energies and polarizabilities
	energies = []
	polarizabilities = []
	
	for fieldStrength in fieldRange:
		print "Calculating energy shift for field strength = %s..." % fieldStrength
		#Reset potential with current intensity
		TotalMatrix = SetupTotalMatrix(fieldStrength)
		
		#Find shifted eigenvalue
		energy = JacobiDavidson(TotalMatrix)

		#Compute polarizability
		energyShift = energy - refEnergy
		polarizability = -2.0 * energyShift / fieldStrength**2

		#Store current energy and polarizability
		energies.append(energy)
		polarizabilities.append(polarizability)

	return fieldRange, polarizabilities, energies

#------------------------------------------------------------------------------------
#                      Matrix Conversion Function
#------------------------------------------------------------------------------------

def GetRadialMatricesCompressedCol(pot, psi):
	localShape = psi.GetData().shape

	#do parallelizaion on angular rank
	repr = psi.GetRepresentation()
	if repr.GetDistributedModel().IsDistributedRank(1) or repr.GetDistributedModel().IsDistributedRank(2):
		raise Exception("Only angular rank can be distributed")

	#Check that the angular basis pairs is diagonal
	for row, col in zip(pot.BasisPairs[0][:,0], pot.BasisPairs[0][:,1]):
		if row != col:
			raise Exception("%i != %i, angular rank must be diagonal for potential %s" % (row, col, pot.Name))

	#stats for each radial matrix
	matrixSize = localShape[1] * localShape[2]
	nonzeroCount = pot.BasisPairs[1].shape[0] * pot.BasisPairs[2].shape[0]

	#Create a list of radial index pairs in the full matrix
	matrixPairs = zeros((nonzeroCount, 2), dtype=int)
	matrixIndex = 0
	for i, (row0, col0) in enumerate(pot.BasisPairs[1]):
		rowIndex0 = (row0 * localShape[2])
		colIndex0 = (col0 * localShape[2]) 
		for j, (row1, col1) in enumerate(pot.BasisPairs[2]):
			rowIndex = rowIndex0 + row1
			colIndex = colIndex0 + col1

			matrixPairs[matrixIndex, 0] = rowIndex
			matrixPairs[matrixIndex, 1] = colIndex
			matrixIndex += 1

	#Sort indexpairs by column
	sortIndices = argsort(matrixPairs[:,1])

	#create colStart- and row-indices required by the col-compressed format
	# colStartIndices is the indices in the compressed matrix where a col starts
	# rowIndices is the row of every element in the compressed matrix
	colStartIndices = zeros(matrixSize+1, dtype=int32)
	rowIndices = zeros(nonzeroCount, dtype=int32)
	prevCol = -1
	for i, sortIdx in enumerate(sortIndices):
		row, col = matrixPairs[sortIdx, :]
		rowIndices[i] = row

		if prevCol != col:
			if prevCol != col -1:
				raise Exception("What? Not a col-compressed format?")
			colStartIndices[col] = i
			prevCol = col
	colStartIndices[-1] = nonzeroCount

	#Create a radial matrix in compressed col format for each angular index
	radialMatrices = []
	localAngularCount = localShape[0]
	for curAngularIndex in range(localAngularCount):
		potentialSlice = pot.PotentialData[curAngularIndex, :, :].flat
		radialMatrix = zeros(nonzeroCount, dtype=complex)
		
		for i, sortIdx in enumerate(sortIndices):
			radialMatrix[i] = potentialSlice[sortIdx]

		radialMatrices.append( radialMatrix )

	return rowIndices, colStartIndices, radialMatrices

				
class RadialTwoElectronPreconditioner:
	def __init__(self, psi):
		self.Rank = psi.GetRank()
		self.psi = psi

	def ApplyConfigSection(self, conf):
		self.OverlapSection = conf.Config.GetSection("OverlapPotential")
		self.PotentialSections = [conf.Config.GetSection(s) for s in conf.potential_evaluation]

	def SetHamiltonianScaling(self, scalingH):
		self.HamiltonianScaling = scalingH

	def SetOverlapScaling(self, scalingS):
		self.OverlapScaling = scalingS

	def GetHamiltonianScaling(self):
		return self.HamiltonianScaling

	def GetOverlapScaling(self):
		return self.OverlapScaling

	def Setup(self, prop):
		"""
		Set up a tensor potential for overlap potential and all other potentials
		and add them together, assuming they have the same layout
		ending up with a potential containing S + scalingH * (P1 + P2 + ...)

		The radial part of this potential is then converted to compressed col storage
		and factorized.
		"""

		#Setup overlap potential
		tensorPotential = prop.BasePropagator.GeneratePotential(self.OverlapSection)
		tensorPotential.PotentialData *= self.GetOverlapScaling()

		#Add all potentials to solver
		scalingH = self.GetHamiltonianScaling()
		for conf in self.PotentialSections:
			#Setup potential in basis
			potential = prop.BasePropagator.GeneratePotential(conf)
			if not tensorPotential.CanConsolidate(potential):
				raise Exception("Cannot consolidate potential %s with overlap-potential" % (potential.Name))
		
			#Add potential
			tensorPotential.PotentialData += scalingH * potential.PotentialData

	
		#Setup radial matrices in CSC format
		tensorPotential.SetupStep(0.0)
		row, colStart, radialMatrices = GetRadialMatricesCompressedCol(tensorPotential, self.psi)

		shape = self.psi.GetRepresentation().GetFullShape()
		matrixSize = shape[1] * shape[2]

		#factorize each matrix
		radialSolvers = []
		for mat in radialMatrices:
			#M = scipy.sparse.csc_matrix((mat, row, colStart))
			#solve = scipy.linsolve.factorized(M)
			#radialSolvers.append(solve)

			solve = SuperLUSolver_2()
			solve.Setup(int(matrixSize), mat, row, colStart)
			radialSolvers.append(solve)

		self.RadialSolvers = radialSolvers

	def Solve(self, psi):
		data = psi.GetData()
		
		angularCount = data.shape[0]
		if angularCount != len(self.RadialSolvers):
			raise Exception("Invalid Angular Count")

		for angularIndex, solve in enumerate(self.RadialSolvers):
			#data[angularIndex,:,:].flat[:] = solve(data[angularIndex,:,:].flatten())
			solve.Solve(data[angularIndex, :, :])
		

