#ifndef REDUCEDSPHERICAL_THETAREPRESENTATION_H
#define REDUCEDSPHERICAL_THETAREPRESENTATION_H

#include "../../common.h"
#include "../orthogonalrepresentation.h"
#include "thetarange.h"

namespace ReducedSpherical
{

/** Represents the wavefunction in an angular (theta) basis
 * Where the wavefunction is symmetric with respect to phi
 * The distribution of (theta) can be chosen when creating the
 * omega range.
 */
class ThetaRepresentation : public OrthogonalRepresentation
{
public:
	ThetaRange Range;                          //The points chosen for the angular grid

	//Constructors:
	ThetaRepresentation() {}
	virtual ~ThetaRepresentation() {}

	virtual Representation<1>::RepresentationPtr Copy()
	{
		return Representation<1>::RepresentationPtr(new ThetaRepresentation(*this));
	}

	void SetupRepresentation(int maxL);

	//Returns the size of the grid
	virtual blitz::TinyVector<int, 1> GetFullShape()
	{
		return Range.GetGrid().extent(0);
	}

	/*
	 * Performs an inner product between two radial wavefunctions
	 * This should probably not be called to often, because a faster version
	 * will be available in SphericalRepresentation
	 */
	virtual std::complex<double> InnerProduct(const Wavefunction<1>& w1, const Wavefunction<1>& w2)
	{
		throw std::runtime_error("ThetaRepresentation::InnerProduct is not implemented");
	}

	/** 
	Returns the portion of the grid local to the current processor.
	**/
	virtual blitz::Array<double, 1> GetGlobalGrid(int rank)
	{
		if (rank != GetBaseRank())
		{
			cout << "Warning: Trying to get the wrong angular rank. Got " << rank << ", expected " << GetBaseRank() <<  endl;
		}
		return Range.GetGrid();
	}

	/** 
	Returns the portion of the grid local to the current processor.
	**/
	virtual blitz::Array<double, 1> GetGlobalWeights(int rank)
	{
		if (rank != GetBaseRank())
		{
			cout << "Warning: Trying to get the wrong angular rank. Got " << rank << ", expected " << GetBaseRank() <<  endl;
		}
		return Range.GetWeights();
	}

	/** Apply config, and set up Range
	  */
	virtual void ApplyConfigSection(const ConfigSection &config);
};

typedef boost::shared_ptr<ThetaRepresentation> ThetaRepresentationPtr;

} //Namespace

#endif

