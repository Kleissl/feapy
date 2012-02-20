# -*- coding: utf-8 -*-
#
# This file is part of feapy - See LICENSE.txt
#
import sys
import math
from itertools import izip

import numpy as np

# check available solvers
try:
    import spmatrix
    import solver
    SOLVER = 'spooles'
except ImportError:
    try:
        from pysparse import spmatrix, superlu
        SOLVER = 'superlu'
    except ImportError:
        raise ImportError("sparse matrix solver not available")

TINY = 1e-36

# dof & boundary condition types
DOFSIZE = 6
Dx, Dy, Dz, Rx, Ry, Rz = range(DOFSIZE)

# boundary condition types
Fx, Fy, Fz, Mx, My, Mz = range(DOFSIZE, 2*DOFSIZE)

# map dof names to index
DOFMAP = (
    ('Dx',Dx), ('Dy',Dy), ('Dz',Dz),
    ('Rx',Rx), ('Ry',Ry), ('Rz',Rz),
)

# map bc names to index
BCMAP = (
    ('Dx',Dx), ('Dy',Dy), ('Dz',Dz),
    ('Rx',Rx), ('Ry',Ry), ('Rz',Rz),
    ('Fx',Fx), ('Fy',Fy), ('Fz',Fz),
    ('Mx',Mx), ('My',My), ('Mz',Mz)
)

# loading directions
globalX, globalY, globalZ = range(3)
localX, localY, localZ = range(globalZ + 1, globalZ + 3 + 1)

class FEError(Exception):
    pass

class List(list):
    '''
    List with index start at 1
    '''
    def __getitem__(self, key):
        return list.__getitem__(self, key - 1)
        
    def __setitem__(self, key, value):
        return list.__setitem__(self, key - 1, value)
    
    def __delitem__(self, key):
        return list.__delitem__(self, key - 1)
    
    def index(self, arg):
        return list.index(arg) + 1

class Transform(np.ndarray):
    def __new__(cls):
        obj = np.ndarray.__new__(cls, (3,3), dtype=float)
        return obj
    
    @classmethod
    def carthesian(cls, a, b):
        '''
        Create transformation matrix for
        a carthesian coordinate system
        defined by two non-orthogonal points.
        '''
        ret = cls()
        
        ax, ay, az = a
        bx, by, bz = b
        
        # normalize a
        dd = math.sqrt(ax**2 + ay**2 + az**2)
        ax /= dd
        ay /= dd
        az /= dd
        
        # dd = dot(a,b)
        dd =ax*bx +  ay*by + az*bz
        
        # b = b - dd*a
        bx = bx - dd*ax
        by = by - dd*ay
        bz = bz - dd*az
        
        # normalize b
        dd = math.sqrt(bx**2 + by**2 + bz**2)
        bx /= dd
        by /= dd
        bz /= dd
        
        # c = a x b
        cx = ay*bz - az*by
        cy = az*bx - ax*bz
        cz = ax*by - ay*bx
        
        ret[0,:] = ax, ay, az
        ret[1,:] = bx, by, bz
        ret[2,:] = cx, cy, cz
        
        return ret
        
class Material(dict):
    pass
    
class Properties(dict):
    pass

class DofSet(list):
    def __init__(self, **kwargs):
            list.__init__(self, [False,]*6)
            self.update(**kwargs)
    
    def __str__(self):
        cls = self.__class__.__name__
        return "%s%s" % (cls, repr(self))
    
    def __repr__(self):
        fmt = "(Dx=%s, Dy=%s, Dz=%s, Rx=%s, Ry=%s, Rz=%s)" 
        args = tuple(str(val) for val in self)
        return fmt % args
    
    def __and__(self, other):
        arg = [a & b for a,b in izip(self,other)]
        ret = DofSet()
        ret[:] = arg
        return ret
    
    def __iand__(self, other):
        for i in range(6):
            self[i] &= other[i]
        return self
    
    def __or__(self, other):
        arg = [a | b for a,b in izip(self,other)]
        ret = DofSet()
        ret[:] = arg
        return ret
    
    def __ior__(self, other):
        for i in range(6):
            self[i] |= other[i]
        return self
    
    def update(self, **kwargs):
        idxmap = dict(DOFMAP)
            
        for name,value in kwargs.iteritems():
            if name in idxmap:
                self[idxmap[name]] = bool(value)
            else:
                raise ValueError("'%s' not a valid DOF" % name)
                
    def reset(self, value = False):
        for i in range(6):
            self[i] = value
    
    def dofPos(self, bitcount):
        '''
        Special access, giving back pos, at which the bitcount-th
        bit (set bit) occurs. If bitcount-th bit is not set at all,
        give back -1
        '''
        b,i = 0,-1
        while b < bitcount:
            i += 1
            if i == 6:
                return -1
            if self[i]:
                b += 1
        
        return i
            
    def count(self, dofrange = 5):
        return sum(self[:dofrange + 1])
        
    def is3DSolid(self):
        return self.elementDimension() == 3 and self.count() == 3
    
    def is3DShell(self):
        return self.count() == 6
    
    def elementDimension(self):
        return int(self[Dx]) + int(self[Dy]) + int(self[Dz])
        
class BoundCon:
    def __init__(self, **kwargs):
        self.value = [0.] * 12
        self.status = [False] * 12
        self.update(**kwargs)
        
    def __str__(self):
        cls = self.__class__.__name__
        return "%s%s" % (cls, repr(self))
    
    def __repr__(self):
        vals = []
        for name,idx in BCMAP:
            if not self.status[idx]:
                continue
            value = self.value[idx]
            vals.append("%s=%g" % (name, value))
            
        arg = ", ".join(vals)
        
        return "(%s)" % arg
    
    def __getitem__(self, key):
        if self.status[key]:
            return self.value[key]
        
        names = dict((value,name) for name,value in BCMAP)
        raise FEError("BC '%s' not active" % names[key])
        
    def __setitem__(self, key, value):
        self.setBC(key, value)
    
    def __delitem__(self, key):
        self.deleteBC(key)
    
    def update(self, **kwargs):
        idxmap = dict(BCMAP)
            
        for name,value in kwargs.iteritems():
            if name in idxmap:
                self.setBC(idxmap[name], value)
            else:
                raise ValueError("'%s' not a valid BC" % name)
            
    def setBC(self, bctype, value):
        assert bctype >= 0 and bctype <= 11
        self.status[bctype] = True
        self.value[bctype] = value
    
    def deleteBC(self, bctype):
        assert bctype >= 0 and bctype <= 11
        self.status[bctype] = False
        self.value[bctype] = 0.
    
    def deleteBounds(self):
        for i in range(6):
            self.status[i] = False
            self.value[i] = 0.
    
    def deleteLoads(self):
        for i in range(6):
            self.status[i + 6] = False
            self.value[i + 6] = 0.
            
    def activeDofSet(self):
        '''
        Returns active Dofs from point of view of BC's
        (from BC's only homogeneous Dofs are inactive).
        '''
        active = DofSet()
        active.reset(True)
        
        for bc in (Dx, Dy, Dz, Rx, Ry, Rz):
            if self.status[bc] and self.value[bc] == 0.:
                active[bc] = False
        
        return active
    
    def activeLoads(self, loads, minRange = 0, maxRange = 12):
        '''
        Returns active Loads, they consist of non-zero
        displacement constraints and forces
        '''
        for i in range(minRange, maxRange):
            if self.status[i] and self.value[i] != 0.:
                loads[i - minRange] = self.value[i]
            else:
                loads[i - minRange] = 0.
        
        return loads

class Node(object):
    def __init__(self, cx = 0., cy = 0., cz = 0., boundCon = None,
                   coordSys = None):
        self.cx = float(cx)
        self.cy = float(cy)
        self.cz = float(cz)
        
        self.dofSet = DofSet()
        self.boundCon = boundCon
        self.coordSys = coordSys
        self.idxG = 0
        
        self.results = None
    
    def __str__(self):
        args = self.cx, self.cy, self.cz
        return '(cx = %g, cy = %g, cz = %g)' % args
    
    def __repr__(self):
        return '%s%s' % (self.__class__.__name__, str(self))
        
    def activeDofSet(self):
        '''
        Return active Dof's evaluated from
        DofSet and homogeneous BC's.
        '''
        if self.boundCon is None:
            return self.dofSet
        else:
            return self.dofSet & self.boundCon.activeDofSet()
    
    def indexGM(self, dof):
        '''
        Input:  certain DOF as int: 0-5 -> x,y,z,rx,ry,rz
        
        Output: global index in GM, if DOF is active
                else function returns -1
        '''
        if dof < 6:
            active = self.activeDofSet()
            if active[dof]:
               return  self.idxG + active.count(dof) - 1

        return -1
    
    def storeResults(self, results):
        '''
        Store deformations of this node from the solution vector
        '''
        self.results = np.zeros((6,), dtype=float)
        
        # Copy the appropriate values for this node
        for i in range(6):
            idx = self.indexGM(i)
            if idx >= 0:
                self.results[i] = results[idx]

class LineLoad:
    """Distributed loads on line elements"""
    def __init__(self, force, direction = localZ):
        self.force = force
        self.direction = direction
    
    def __str__(self):
        name = self.__class__.__name__
        direction = {
            localX  : 'localX',
            localY  : 'localY',
            localZ  : 'localZ',
            globalX : 'globalX',
            globalY : 'globalY',
            globalZ : 'globalZ'
        }[self.direction]
        
        args = name, self.force, direction
        return "%s(force=%g, directon=%s)" % args
    
    __repr__ = __str__

class NonStructualElement(object):
    '''
    Base object for all non structural elements.
    '''
    
class Element(object):
    '''
    Base object for all structural elements.
    '''
    def __str__(self):
        return '()'
    
    def __repr__(self):
        return '%s%s' % (self.__class__.__name__, str(self))
        
    def sizeOfEM(self):
        '''
        Returns the size of the element matrix.
        '''
        return self.dofSet.count() * self.nodeCount
        
    def evalMass(self):
        '''
        Eval mass of an element, based on volume calculation
        '''
        self.volume() * self.material['rho']
        
    def setNodeDofs(self):
        '''
        Compare the existing NodeDofVec of every node with the DofVec
        write the more free one back to NodeDofVec
        '''
        for node in self.nodes:
            node.dofSet |= self.dofSet
    
    def transformEM(self, K):
        '''
        Transform element matrix (EM), if any nodes of this element
        have rotated coord systems.
        '''
        rotated = []
        
        for node in self.nodes:
            if not node.coordSys is None:
                rotated.append(node)
        
        if rotated:
            # Create transformation matrix T, first as identity matrix
            T = np.eye(K.shape[0], dtype=float)
            dofs =  self.dofSet.count()
            
            for idx,node in enumerate(rotated):
                # TODO: Check for not allowed coordinate system rotations for 2D models
                
                # Get rotation matrix of coord sys of this node
                Tn = node.coordSys

                # Inverse Tn
                Tn = Tn.T
                
                # Eval first index of T to be modified
                posT = idx * dofs
                
                # Replace vals of T with vals from Tni at appropriate places
                # number of DOF's of this element
                dofs1 = dofs
                
                # number of DOF's for "first three DOF entries" of this element
                dofs2 = min(dofs1, 3)
                
                # Replace vals for first three DOF's of actual node
                for i in range(dofs2):
                    for j in range(dofs2):
                        T[posT + i, posT + j] = Tn[i,j]
                
                # Replace vals for second three DOF's of actual node
                for i in range(3, dofs1):
                    for j in range(3, dofs1):
                        T[posT + i, posT + j] = Tn[i - 3,j - 3]
                
            # Eval transformation
            K = np.dot(T.T,np.dot(K,T))
                
        return K
        
    def calcEnvelope(self, envelope):
        '''
        Implementation of function to evaluate influence of
        an element on envelope and profile
        '''
        # Loop through stiffness matrix of element, on node level
        swapped = False
        for i in range(self.nodeCount):
            # number of active dofs of this node
            activedofi = self.nodes[i].activeDofSet().count()
            # Do only something if this node has any active DOF's
            if activedofi < 0:
                continue
            # first global index of this node
            gmi = self.nodes[i].idxG
            
            # Loop through lower half stiffness matrix of element, on node level
            for j in range(0, i + 1):
                # number of active dofs of this node
                activedofj = self.nodes[j].activeDofSet().count()
                # Do only something if this node has any active DOF's
                if activedofj < 0:
                    continue
                # first global index of this node
                gmj = self.nodes[j].idxG
                
                # Check bandwidthes for all lines in GSM that get influenced from Node i
                for dof in range(activedofi):
                    linebandwidth = gmi - gmj + 1 + dof
                    if linebandwidth > envelope[ gmi + dof ]:
                        envelope[ gmi + dof ] = linebandwidth
                    
                # if considered node is in the upper half of symmetric GSM swap indices
                if j > i:
                    swapped = True
                    i,j = j,i
                    activedofi,activedofj = activedofj,activedofi
                
                # Swap indices back for further use
                if swapped:
                    swapped = False
                    i,j = j,i
                    activedofi,activedofj = activedofj,activedofi
                
    def assembleElementK(self, GM):
        '''
        Implementation of Assembly of one element into global structure
        '''
        dofset = self.dofSet
        dofsize = dofset.count()
        
        # Evaluate stiffness matrix of element
        K = self.calcK()
        
        # Transform EM, if there are any rotated nodal coordinate systems
        K = self.transformEM(K)
        
        # loop over lower triangle of symmetric K
        swapped = False
        for i in range(self.sizeOfEM()):
            # nodenr in this element
            nodenr = int(i / dofsize)
            # dofnr-th DOF is looked at right now
            dofnr  = i % dofsize + 1
            # this corresponds to dofpos (x,y,z,rx,ry,rz)
            dofpos = dofset.dofPos(dofnr)
            # Get appropriate globMat row
            row = self.nodes[nodenr].indexGM(dofpos)
            # If considered DOF is active (else row = -1)
            if row < 0:
                continue
                
            # loop over lower triangle of symmetric K
            for j in range(i + 1):
                # nodenr in this element
                nodenr = int(j / dofsize)
                # dofnr-th DOF is looked at right now
                dofnr  = j % dofsize + 1
                # this corresponds to dofpos (x,y,z,rx,ry,rz)
                dofpos = dofset.dofPos(dofnr)
                # Get appropriate globMat row
                col = self.nodes[nodenr].indexGM(dofpos)
                # If considered DOF is active (else col= -1)
                if col < 0:
                    continue
                # if considered dof is located in upper half of globMat, swap indices
                if col > row:
                    swapped = True
                    col,row = row,col
                
                # Add K(i,j) to globMat
                GM[row,col] += K[i,j]
                
                if swapped:
                    swapped = False
                    col,row = row,col
    
    def assembleElementM(self, GM, lumped = False):
        '''
        Implementation of Assembly of one element into global structure
        '''
        dofset = self.dofSet
        dofsize = dofset.count()
        
        # Evaluate mass matrix of element
        M = self.calcM(lumped)
        
        # Transform EM, if there are any rotated nodal coordinate systems
        M = self.transformEM(M)
        
        # loop over lower triangle of symmetric M
        swapped = False
        for i in range(self.sizeOfEM()):
            # nodenr in this element
            nodenr = int(i / dofsize)
            # dofnr-th DOF is looked at right now
            dofnr  = i % dofsize + 1
            # this corresponds to dofpos (x,y,z,rx,ry,rz)
            dofpos = dofset.dofPos(dofnr)
            # Get appropriate globMat row
            row = self.nodes[nodenr].indexGM(dofpos)
            # If considered DOF is active (else row = -1)
            if row < 0:
                continue
                
            # loop over lower triangle of symmetric M
            for j in range(i + 1):
                # nodenr in this element
                nodenr = int(j / dofsize)
                # dofnr-th DOF is looked at right now
                dofnr  = j % dofsize + 1
                # this corresponds to dofpos (x,y,z,rx,ry,rz)
                dofpos = dofset.dofPos(dofnr)
                # Get appropriate globMat row
                col = self.nodes[nodenr].indexGM(dofpos)
                # If considered DOF is active (else col= -1)
                if col < 0:
                    continue
                # if considered dof is located in upper half of globMat, swap indices
                if col > row:
                    swapped = True
                    col,row = row,col
                
                # Add K(i,j) to globMat
                GM[row,col] += M[i,j]
                
                
                if swapped:
                    swapped = False
                    col,row = row,col
class FE(object):
    def __init__(self, nodes = None, elements = None):
        self.nodes = List()
        self.elements = List()
        
        self.GK = None
        self.GM = None
        self.step = 0
        self.dofcount = 0
        self.envelope = None
        self.nodalforces = None
        self.elementforces = None
        
        self.ev = None
        self.evec = None
        
        if not nodes is None:
            self.nodes.extend(nodes)
        
        if not elements is None:
            self.elements.extend(elements)
    
    def eall(self):
        '''
        Create elset with all elements
        '''
        return set(xrange(1, len(self.elements) + 1))
    
    def nall(self):
        '''
        Create nset with all nodes
        '''
        return set(xrange(1, len(self.nodes) + 1))
        
    def validate(self):
        '''
        Validate FE model
        '''
        # check if all nodes are connected
        seen = set()
        for element in self.elements:
            seen.update(element.nodes)
        
        if (set(self.nodes) - seen):
            raise FEError("All nodes not connceted to elements")
        
        # check if all degrees are constrained
        dofs = DofSet(Dx=True, Dy=True, Dz=True)
        for node in self.nodes:
            dofs &= node.activeDofSet()
        
        if dofs.count(2) != 0:
            raise FEError("Structure uncostrained")
        
        # check elements
        emap = set()
        for eid, element in enumerate(self.elements, start = 1):
            element.validate()
            
            connection = tuple(element.nodes)
            if connection in emap:
                raise FEError('Duplicate element definition %d' % eid)
            else:
                emap.add(connection)
        
    def solve(self):
        # Link node DOF's to GSM index
        self.linkNodes()
        
        # create global matrix and fill with element data
        self.assembleElementK()
        
        # Eval load vector and apply inhomogeneous BC's
        self.applyLoads()
        
        # solve
        self.staticSolver()
        
        # store deformation in nodes
        self.storeNodalResults()
        
        # calculate reaction forces
        self.solveReactions()
        
    def linkNodes(self):
        '''
        Link nodes to global matrix and
        give back global matrix size.
        '''
        
        # reset NodeDofSets
        for node in self.nodes:
            node.dofSet.reset()
            node.idxG = 0
        
        # Set node DOF vectors based on DOF's of elements
        for element in self.elements:
            element.setNodeDofs()
        
        # Set index for each node, pointing to first DOF in the GM
        # The active Dofs of each node are determined through GetActiveDof(),
        # which takes into account the NodeDofVec and the homogeneous BC's of a node
        idx = 0
        for node in self.nodes:
            node.idxG = idx
            idx += node.activeDofSet().count()
        
        # Give back Size of GM to be created later on
        self.dofcount = idx
        
    def evalEnvelope(self):
        '''
        Evaluation of envelope and profile of the GM
        '''
        self.envelope = np.zeros((self.dofcount,), dtype=int)
        
        for element in self.elements:
            element.calcEnvelope(self.envelope)
        
        # envelope of first row is per definition equal 1
        self.envelope[ 0 ] = 1
        
        return np.sum(self.envelope)
    
    def assembleElementK(self):
        '''
        Assembly: Evaluate element stiffness matrix and fill GM.
        '''
        # Eval envelope and profile of GSM
        profile = self.evalEnvelope()
        
        # Evaluate ESM's and assemble them to GSM
        if SOLVER == 'spooles':
            self.GK = spmatrix.DOK((self.dofcount,self.dofcount))
        elif SOLVER == 'superlu':
            self.GK = spmatrix.ll_mat_sym(self.dofcount, profile)
        else:
            raise FEError('unknown solver')
            
        for element in self.elements:
            element.assembleElementK(self.GK)
    
    def assembleElementM(self):
        '''
        Assembly: Evaluate element mass matrix and fill GM.
        '''
        # Eval envelope and profile of GSM
        profile = self.evalEnvelope()
        
        # Evaluate ESM's and assemble them to GSM
        if SOLVER == 'spooles':
            self.GM = spmatrix.DOK((self.dofcount,self.dofcount))
        elif SOLVER == 'superlu':
            self.GM = spmatrix.ll_mat_sym(self.dofcount, profile)
        else:
            raise FEError('unknown solver')
            
        for element in self.elements:
            element.assembleElementM(self.GM)
            
    def applyLoads(self):
        '''
        Apply homogeonous boundary conditions.
        '''
        # Set Force vector to zero
        self.nodalforces = np.zeros((self.dofcount,), dtype=float)
        forces = self.nodalforces
        
        nodeloads = np.zeros((12,), dtype=float)
        
        # check nodes for loads
        for node in self.nodes:
            if node.boundCon is None:
                continue
            # Get active loads for that node
            node.boundCon.activeLoads(nodeloads)
            # Loop over the 6 DOF's
            for i in range(6):
                # Get global index of this DOF
                idx = node.indexGM(i)
                # Check if this DOF is active
                if idx < 0:
                    continue
                
                # write nodal force to global load vector
                force = nodeloads[i + 6]
                if force != 0.:
                    forces[idx] += force
                
                load = nodeloads[i]
                if load != 0.:
                    # loop over all DOF's
                    for j in range(len(forces)):
                        if j < idx and envelope[idx] > idx - j:
                            # upper triangle
                            forces[j] -= load * self.GK[idx,j]
                            self.GK[idx,j] = 0.
                        elif envelope[j] > j - idx:
                            # lower triangle
                            forces[j] -= load * self.GK[j,idx]
                            self.GK[j,idx] = 0.
                    
                    # for the actual force value:
                    forces[idx] = load
                    # for globMat(gsmindex, gsmindex)
                    self.GK[idx,idx] = 1.
        
        # check for element loads
        for element in self.elements:
            if not element.loads:
                continue
            
            dofsize = element.dofSet.count()
            nodeloads.resize((dofsize * element.nodeCount,))
            nodeloads.fill(0.)
            
            element.calcNodalForces(nodeloads)
            
            for i, node in enumerate(element.nodes):
                for dof in range(dofsize):
                    # Get global index of this DOF
                    idx = node.indexGM(dof)
                    # Check if this DOF is active
                    if idx < 0:
                        continue
                    
                    forces[idx] += nodeloads[i*dofsize + dof]
    
    def modalSolver(self, nev = 3):
        if SOLVER == 'spooles':
            print >>sys.stderr, "The arpack solver using spooles factoring"
            print >>sys.stderr, "does currently not work correctly"
            print >>sys.stderr, "revert to use pysparse"
        
        from pysparse import jdsym, itsolvers, precon, spmatrix
        
        # copy matrixes
        GK = self.GK
        A = spmatrix.ll_mat_sym(self.dofcount, len(GK))
        for row, col in GK:
            A[row,col] = GK[row,col]
        
        GM = self.GM
        M = spmatrix.ll_mat_sym(self.dofcount, len(GM))
        for row, col in GM:
            M[row,col] = GM[row,col]
        
        # Atau = A + tau*M
        tau = -1.0
        Atau = A.copy()
        Atau.shift(tau, M)
        K = precon.jacobi(Atau)
        
        # convert to skyline
        A = A.to_sss()
        M = M.to_sss()
        
        # solve
        k_conv, lmbd, Q, it, it_innser  =  \
            jdsym.jdsym(A, M, K, nev, tau,
                        1e-4, 4*self.dofcount, itsolvers.qmrs,
                        jmin=5, jmax=10, clvl=0, strategy=1)
        
        # eigen values
        return lmbd
            
    def staticSolver(self):
        self.solution = np.zeros((self.dofcount,), dtype=float)
        forces = self.nodalforces
        
        if SOLVER == 'spooles':
            spooles = solver.Spooles(self.GK, symflag = 0)
            self.solution[:] = forces
            spooles.solve(self.solution)

        elif SOLVER == 'superlu':
            mat = self.GK.to_csr()
            LU = superlu.factorize(mat, permc_spec=2, diag_pivot_thresh=0.)
            LU.solve(forces, self.solution)
        
        else:
            raise FEError('unknown solver')
        
    def solveReactions(self, nset = None):
        '''
        Calculate the reaction forces and store
        in nodes.
        
        By default reaction are calculated over all nodes.
        Alternative a set of node ids can be supplied
        to restrict the calculation.
        
        Return summation over selected nodes.
        '''
        if nset is None:
            nset = set(xrange(1, len(self.nodes) + 1))
        
        # loop nodes and clear reactions
        nmap = set()
        for nid in nset:
            node = self.nodes[nid]
            nmap.add(node)
            node.reaction = np.zeros((6,), dtype = float)
        
        total = np.zeros((3,), dtype = float)
        
        resv = np.zeros((12,), dtype=float)
        for element in self.elements:
            # filter out elements
            for node in element.nodes:
                if node in nmap:
                    break
            else:
                continue
            
            # element dofset
            dofset = element.dofSet
            ndofs = dofset.count()
            
            # resize results vector
            dofsize = ndofs * element.nodeCount
            resv.resize((dofsize,))
            resv[:] = 0.
            
            # every node of the element
            count, loop = 0, 0
            for node in element.nodes:
                if node.coordSys is None:
                    # first DoF:ux
                    if dofset.count(0):
                        resv[count] = node.results[0]
                        count += 1
                    # through other DoF uy, uz, Mx, My, Mz
                    for i in range(5):
                        if dofset.count(i + 1) - dofset.count(i) == 1:
                            resv[count] = node.results[i + 1]
                            count += 1
                else:
                    dof = np.zeros((3,), dtype=float)
                    
                    # first DoF:ux
                    if dofset.count(0):
                        dof[0] = node.results[0]
                        loop += 1
                    else:
                        dof[0] = 0.
                        
                    # through other DoF uy, uz
                    for i in range(1,3):
                        if dofset.count(i) - dofset.count(i - 1) == 1:
                            dof[i] = node.results[i]
                            loop += 2
                        else:
                            dof[i] = 0.
                    
                    # Get rotation matrix for this node
                    T = node.coordSys
                    
                    # Transform local DoF in Global DoF for ux, uy and uz
                    doft = np.dot(T.T, dof)
                    
                    # check which case ... Beam, Shell, Solid...
                    if loop >= 1:
                        resv[count] = doft[0]
                        count += 1
                    
                    if loop >= 3:
                        resv[count] = doft[1]
                        count += 1
                    
                    if loop == 5:
                        resv[count] = doft[2]
                        count += 1
                    
                    # through other DoF: Mx, My, Mz
                    loop = 0
                    for i in range(3,6):
                        if dofset.count(i) - dofset.count(i - 1) == 1:
                            dof[i-3] = node.results[i]
                            loop += 2
                        else:
                            dof[i-3] = 0.
                            
                    # transform in global Coord
                    doft = np.dot(T, dof)
                    
                    if loop == 2:
                        resv[count] = doft[2]
                    elif loop == 6:
                        resv[count + 0] = doft[0]
                        resv[count + 1] = doft[1]
                        resv[count + 2] = doft[2]
                        count += 3
                    
            # reaction =  global Stiffnessmatrix * global DoF
            K = element.calcK()
            
            reaction = np.dot(K, resv)
            
            # Correct forces from eqivalent forces line loads
            iforces = element.calcNodalForces()
        
            # write results back to selected nodes
            k = -1
            for node in element.nodes:
                if not node in nmap:
                    # skip node
                    k += ndofs
                    continue
                
                ndof = node.activeDofSet()
                
                for j in range(6):
                    if dofset[j]:
                        k += 1
                            
                    if ndof[j] and node.coordSys is None:
                        continue
                        
                    node.reaction[j] += reaction[k] - iforces[k]
                    # update total reaction force
                    if j < 3:
                        total[j] += reaction[k] - iforces[k]
        
        return total
                    
    def storeNodalResults(self):
        '''
        Store deformation results in nodes
        '''
        for node in self.nodes:
            node.storeResults(self.solution)

if __name__ == '__main__':
    m = Transform.carthesian((1,0,1), (1,-1,1))
    print m
    
    v = np.dot(m, (1.,0.,0.))
    print v
    print np.dot(m.T, v)
    