"""
Squeak model.

    W_Object
        W_SmallInteger        
        W_Float
        W_AbstractObjectWithIdentityHash
            W_AbstractObjectWithClassReference
                W_PointersObject 
                W_BytesObject
                W_WordsObject
            W_CompiledMethod

W_BlockContext and W_MethodContext classes have been replaced by functions
that create W_PointersObjects of correct size with attached shadows.
"""
import sys
from spyvm.tool.bitmanipulation import splitter
from spyvm import constants, error

from rpython.rlib import rrandom, objectmodel
from rpython.rlib.rarithmetic import intmask, r_uint
from rpython.tool.pairtype import extendabletype
from rpython.rlib.objectmodel import instantiate

class W_Object(object):
    """Root of Squeak model, abstract."""
    __slots__ = ()    # no RPython-level instance variables allowed in W_Object

    def size(self):
        """Return bytesize that conforms to Blue Book.
        
        The reported size may differ from the actual size in Spy's object
        space, as memory representation varies depending on PyPy translation."""
        return 0

    def varsize(self, space):
        """Return bytesize of variable-sized part.

        Variable sized objects are those created with #new:."""
        return self.size(space)

    def primsize(self, space):
        # TODO remove this method
        return self.size()

    def getclass(self, space):
        """Return Squeak class."""
        raise NotImplementedError()

    def gethash(self):
        """Return 31-bit hash value."""
        raise NotImplementedError()

    def at0(self, space, index0):
        """Access variable-sized part, as by Object>>at:.

        Return value depends on layout of instance. Byte objects return bytes,
        word objects return words, pointer objects return pointers. Compiled method are
        treated special, if index0 within the literalsize returns pointer to literal,
        otherwise returns byte (ie byte code indexing starts at literalsize)."""
        raise NotImplementedError()

    def atput0(self, space, index0, w_value):
        """Access variable-sized part, as by Object>>at:put:.

        Semantics depend on layout of instance. Byte objects set bytes,
        word objects set words, pointer objects set pointers. Compiled method are
        treated special, if index0 within the literalsize sets pointer to literal,
        otherwise patches bytecode (ie byte code indexing starts at literalsize)."""
        raise NotImplementedError()

    def fetch(self, space, n0):
        """Access fixed-size part, maybe also variable-sized part (we have to
        consult the Blue Book)."""
        # TODO check the Blue Book
        raise NotImplementedError()
        
    def store(self, space, n0, w_value):    
        """Access fixed-size part, maybe also variable-sized part (we have to
        consult the Blue Book)."""
        raise NotImplementedError()

    def invariant(self):
        return True

    def shadow_of_my_class(self, space):
        """Return internal representation of Squeak class."""
        return self.getclass(space).as_class_get_shadow(space)

    def is_same_object(self, other):
        """Compare object identity. This should be used instead of directly
        using is everywhere in the interpreter, in case we ever want to
        implement it differently (which is useful e.g. for proxies). Also,
        SmallIntegers and Floats need a different implementation."""
        return self is other

    def become(self, other):
        """Become swaps two objects.
           False means swapping failed"""
        return False

    def clone(self, space):
        raise NotImplementedError

class W_SmallInteger(W_Object):
    """Boxed integer value"""
    # TODO can we tell pypy that its never larger then 31-bit?
    __slots__ = ('value',)     # the only allowed slot here

    def __init__(self, value):
        self.value = value

    def getclass(self, space):
        return space.w_SmallInteger

    def gethash(self):
        return self.value

    def invariant(self):
        return isinstance(self.value, int) and self.value < 0x8000

    def __repr__(self):
        return "W_SmallInteger(%d)" % self.value

    def is_same_object(self, other):
        # TODO what is correct terminology to say that identity is by value?
        if not isinstance(other, W_SmallInteger):
            return False
        return self.value == other.value

    def __eq__(self, other):
        if not isinstance(other, W_SmallInteger):
            return False
        return self.value == other.value

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return self.value

    def clone(self, space):
        return self

class W_Float(W_Object):
    """Boxed float value."""
    def __init__(self, value):
        self.value = value

    def getclass(self, space):
        """Return Float from special objects array."""
        return space.w_Float

    def gethash(self):
        return 41    # XXX check this

    def invariant(self):
        return self.value is not None        # XXX but later:
        #return isinstance(self.value, float)
    def __repr__(self):
        return "W_Float(%f)" % self.value

    def is_same_object(self, other):
        if not isinstance(other, W_Float):
            return False
        # TODO is that correct in Squeak?
        return self.value == other.value

    def __eq__(self, other):
        if not isinstance(other, W_Float):
            return False
        return self.value == other.value

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.value)

    def clone(self, space):
        return self

class W_AbstractObjectWithIdentityHash(W_Object):
    """Object with explicit hash (ie all except small
    ints and floats)."""
    #XXX maybe this is too extreme, but it's very random
    hash_generator = rrandom.Random()
    UNASSIGNED_HASH = sys.maxint

    hash = UNASSIGNED_HASH # default value

    def setchar(self, n0, character):
        raise NotImplementedError()

    def gethash(self):
        if self.hash == self.UNASSIGNED_HASH:
            self.hash = hash = intmask(self.hash_generator.genrand32()) // 2
            return hash
        return self.hash

    def invariant(self):
        return isinstance(self.hash, int)

    def _become(self, w_other):
        self.hash, w_other.hash = w_other.hash, self.hash

class W_AbstractObjectWithClassReference(W_AbstractObjectWithIdentityHash):
    """Objects with arbitrary class (ie not CompiledMethod, SmallInteger or
    Float)."""

    def __init__(self, w_class):
        if w_class is not None:     # it's None only for testing
            assert isinstance(w_class, W_PointersObject)
        self.w_class = w_class

    def getclass(self, space):
        assert self.w_class is not None
        return self.w_class

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, self)

    def __str__(self):
        if isinstance(self, W_PointersObject) and self._shadow is not None:
            return self._shadow.getname()
        else:
            name = None
            if self.w_class._shadow is not None:
                name = self.w_class._shadow.name
            return "a %s" % (name or '?',)

    def invariant(self):
        return (W_AbstractObjectWithIdentityHash.invariant(self) and
                isinstance(self.w_class, W_PointersObject))

    def _become(self, w_other):
        self.w_class, w_other.w_class = w_other.w_class, self.w_class
        W_AbstractObjectWithIdentityHash._become(self, w_other)
        

class W_PointersObject(W_AbstractObjectWithClassReference):
    """Common object."""
    
    _shadow = None # Default value

    def __init__(self, w_class, size):
        """Create new object with size = fixed + variable size."""
        W_AbstractObjectWithClassReference.__init__(self, w_class)
        self._vars = [w_nil] * size

    def at0(self, space, index0):
        # To test, at0 = in varsize part
        return self.fetch(space, index0+self.instsize(space))

    def atput0(self, space, index0, w_value):
        # To test, at0 = in varsize part
        self.store(space, index0 + self.instsize(space), w_value)

    def fetch(self, space, n0):
        if self._shadow is not None:
            return self._shadow.fetch(n0)
        return self._fetch(n0)

    def _fetch(self, n0):
        return self._vars[n0]
        
    def store(self, space, n0, w_value):    
        if self._shadow is not None:
            return self._shadow.store(n0, w_value)
        return self._store(n0, w_value)

    def _store(self, n0, w_value):
        self._vars[n0] = w_value


    def varsize(self, space):
        return self.size() - self.instsize(space)

    def instsize(self, space):
        return self.shadow_of_my_class(space).instsize()

    def primsize(self, space):
        return self.varsize(space)

    def size(self):
        if self._shadow is not None:
            return self._shadow.size()
        return self._size()

    def _size(self):
        return len(self._vars)

    def invariant(self):
        return (W_AbstractObjectWithClassReference.invariant(self) and
                isinstance(self._vars, list))

    def store_shadow(self, shadow):
        self._shadow = shadow

    @objectmodel.specialize.arg(2)
    def attach_shadow_of_class(self, space, TheClass):
        shadow = TheClass(space, self)
        self._shadow = shadow
        shadow.attach_shadow()
        return shadow

    @objectmodel.specialize.arg(2)
    def as_special_get_shadow(self, space, TheClass):
        shadow = self._shadow
        if shadow is None:
            shadow = self.attach_shadow_of_class(space, TheClass)
        elif not isinstance(shadow, TheClass):
            shadow.detach_shadow()
            shadow = self.attach_shadow_of_class(space, TheClass)
        shadow.sync_shadow()
        return shadow

    def get_shadow(self, space):
        from spyvm.shadow import AbstractShadow
        return self.as_special_get_shadow(space, AbstractShadow)

    def as_class_get_shadow(self, space):
        from spyvm.shadow import ClassShadow
        return self.as_special_get_shadow(space, ClassShadow)

    def as_blockcontext_get_shadow(self, space):
        from spyvm.shadow import BlockContextShadow
        return self.as_special_get_shadow(space, BlockContextShadow)

    def as_methodcontext_get_shadow(self, space):
        from spyvm.shadow import MethodContextShadow
        return self.as_special_get_shadow(space, MethodContextShadow)

    def as_context_get_shadow(self, space):
        from spyvm.shadow import ContextPartShadow
        # XXX TODO should figure out itself if its method or block context
        if self._shadow is None:
            if ContextPartShadow.is_block_context(self, space):
                return self.as_blockcontext_get_shadow(space)
            return self.as_methodcontext_get_shadow(space)
        return self.as_special_get_shadow(space, ContextPartShadow)

    def as_methoddict_get_shadow(self, space):
        from spyvm.shadow import MethodDictionaryShadow
        return self.as_special_get_shadow(space, MethodDictionaryShadow)

    def become(self, w_other):
        if not isinstance(w_other, W_PointersObject):
            return False
        self._vars, w_other._vars = w_other._vars, self._vars
        self._shadow, w_other._shadow = w_other._shadow, self._shadow
        W_AbstractObjectWithClassReference._become(self, w_other)
        return True
        
    def clone(self, space):
        w_result = W_PointersObject(self.w_class, len(self._vars))
        w_result._vars = [self.fetch(space, i) for i in range(len(self._vars))]
        return w_result

class W_BytesObject(W_AbstractObjectWithClassReference):
    def __init__(self, w_class, size):
        W_AbstractObjectWithClassReference.__init__(self, w_class)
        self.bytes = ['\x00'] * size

    def at0(self, space, index0):
        return space.wrap_int(ord(self.getchar(index0)))
       
    def atput0(self, space, index0, w_value):
        self.setchar(index0, chr(space.unwrap_int(w_value)))

    def getchar(self, n0):
        return self.bytes[n0]
    
    def setchar(self, n0, character):
        assert len(character) == 1
        self.bytes[n0] = character

    def size(self):
        return len(self.bytes)    

    def __str__(self):
        return self.as_string()

    def __repr__(self):
        return "<W_BytesObject %r>" % (self.as_string(),)

    def as_string(self):
        return "".join(self.bytes)

    def invariant(self):
        if not W_AbstractObjectWithClassReference.invariant(self):
            return False
        for c in self.bytes:
            if not isinstance(c, str) or len(c) != 1:
                return False
        return True

    def is_same_object(self, other):
        # XXX this sounds very wrong to me
        if not isinstance(other, W_BytesObject):
            return False
        return self.bytes == other.bytes

    def clone(self, space):
        w_result = W_BytesObject(self.w_class, len(self.bytes))
        w_result.bytes = list(self.bytes)
        return w_result

class W_WordsObject(W_AbstractObjectWithClassReference):
    def __init__(self, w_class, size):
        W_AbstractObjectWithClassReference.__init__(self, w_class)
        self.words = [r_uint(0)] * size
        
    def at0(self, space, index0):
        val = self.getword(index0)
        return space.wrap_uint(val)
 
    def atput0(self, space, index0, w_value):
        word = space.unwrap_uint(w_value)
        self.setword(index0, word)

    def getword(self, n):
        return self.words[n]
        
    def setword(self, n, word):
        self.words[n] = r_uint(word)

    def size(self):
        return len(self.words)   

    def invariant(self):
        return (W_AbstractObjectWithClassReference.invariant(self) and
                isinstance(self.words, list))

    def clone(self, space):
        w_result = W_WordsObject(self.w_class, len(self.words))
        w_result.words = list(self.words)
        return w_result

# XXX Shouldn't compiledmethod have class reference for subclassed compiled
# methods?
class W_CompiledMethod(W_AbstractObjectWithIdentityHash):
    """My instances are methods suitable for interpretation by the virtual machine.  This is the only class in the system whose instances intermix both indexable pointer fields and indexable integer fields.

    The current format of a CompiledMethod is as follows:

        header (4 bytes)
        literals (4 bytes each)
        bytecodes  (variable)
    """

### Extension from Squeak 3.9 doc, which we do not implement:
###        trailer (variable)
###    The trailer has two variant formats.  In the first variant, the last
###    byte is at least 252 and the last four bytes represent a source pointer
###    into one of the sources files (see #sourcePointer).  In the second
###    variant, the last byte is less than 252, and the last several bytes
###    are a compressed version of the names of the method's temporary
###    variables.  The number of bytes used for this purpose is the value of
###    the last byte in the method.

    def __init__(self, bytecount=0, header=0):
        self.setheader(header)
        self.bytes = ["\x00"] * bytecount

    def become(self, w_other):
        if not isinstance(w_other, W_CompiledMethod):
            return False
        self.argsize, w_other.argsize = w_other.argsize, self.argsize
        self.primitive, w_other.primitive = w_other.primitive, self.primitive
        self.literals, w_other.literals = w_other.literals, self.literals
        self.tempsize, w_other.tempsize = w_other.tempsize, self.tempsize
        self.bytes, w_other.bytes = w_other.bytes, self.bytes
        self.header, w_other.header = w_other.header, self.header
        self.literalsize, w_other.literalsize = w_other.literalsize, self.literalsize
        self.w_compiledin, w_other.w_compiledin = w_other.w_compiledin, self.w_compiledin
        self.islarge, w_other.islarge = w_other.islarge, self.islarge
        W_AbstractObjectWithIdentityHash._become(self, w_other)
        return True

    def compiledin(self):  
        if self.w_compiledin is None:
            from spyvm import wrapper
            # (Blue book, p 607) All CompiledMethods that contain
            # extended-super bytecodes have the clain which they are found as
            # their last literal variable.   
            # Last of the literals is an association with compiledin
            # as a class
            w_association = self.literals[-1]
            # XXX XXX XXX where to get a space from here
            association = wrapper.AssociationWrapper(None, w_association)
            self.w_compiledin = association.value()
        return self.w_compiledin

    def getclass(self, space):
        return space.w_CompiledMethod

    def getliteral(self, index):
                                    # We changed this part
        return self.literals[index] #+ constants.LITERAL_START]

    def getliteralsymbol(self, index):
        w_literal = self.getliteral(index)
        assert isinstance(w_literal, W_BytesObject)
        return w_literal.as_string()    # XXX performance issue here

    def create_frame(self, space, receiver, arguments, sender = None):
        from spyvm import shadow
        assert len(arguments) == self.argsize
        w_new = shadow.MethodContextShadow.make_context(
                space, self, receiver, arguments, sender)
        return w_new

    def __str__(self):
        from spyvm.interpreter import BYTECODE_TABLE
        j = 1
        retval = "\n\nBytecode:\n---------------------\n"
        for i in self.bytes:
            retval += str(j) + ": " + BYTECODE_TABLE[ord(i)].__name__ + " " + str(ord(i)) + "\n"
            j += 1
        return retval + "\n---------------------\n"

    def invariant(self):
        return (W_Object.invariant(self) and
                hasattr(self, 'literals') and
                self.literals is not None and 
                hasattr(self, 'bytes') and
                self.bytes is not None and 
                hasattr(self, 'argsize') and
                self.argsize is not None and 
                hasattr(self, 'tempsize') and
                self.tempsize is not None and 
                hasattr(self, 'primitive') and
                self.primitive is not None)       

    def size(self):
        return self.headersize() + self.getliteralsize() + len(self.bytes) 

    def getliteralsize(self):
        return self.literalsize * constants.BYTES_PER_WORD

    def bytecodeoffset(self):
        return self.getliteralsize() + self.headersize()

    def headersize(self):
        return constants.BYTES_PER_WORD

    def getheader(self):
        return self.header

    def setheader(self, header):
        """Decode 30-bit method header and apply new format.

        (index 0)  9 bits: main part of primitive number   (#primitive)
        (index 9)  8 bits: number of literals (#numLiterals)
        (index 17) 1 bit:  whether a large frame size is needed (#frameSize)
        (index 18) 6 bits: number of temporary variables (#numTemps)
        (index 24) 4 bits: number of arguments to the method (#numArgs)
        (index 28) 1 bit:  high-bit of primitive number (#primitive)
        (index 29) 1 bit:  flag bit, ignored by the VM  (#flag)
        """
        primitive, literalsize, islarge, tempsize, numargs, highbit = (
            splitter[9,8,1,6,4,1](header))
        primitive = primitive + (highbit << 10) ##XXX todo, check this
        self.literalsize = literalsize
        self.literals = [w_nil] * self.literalsize
        self.header = header
        self.argsize = numargs
        self.tempsize = tempsize
        assert self.tempsize >= self.argsize
        self.primitive = primitive
        self.w_compiledin = None
        self.islarge = islarge

    def literalat0(self, space, index0):
        if index0 == 0:
            return space.wrap_int(self.getheader())
        else:
            return self.literals[index0-1]

    def literalatput0(self, space, index0, w_value):
        if index0 == 0:
            header = space.unwrap_int(w_value)
            self.setheader(header)
        else:
            self.literals[index0-1] = w_value

    def store(self, space, index0, w_v):
        self.atput0(space, index0, w_v)

    def at0(self, space, index0):
        if index0 <= self.getliteralsize():
            return self.literalat0(space, index0 / constants.BYTES_PER_WORD)
        else:
            # From blue book:
            # The literal count indicates the size of the
            # CompiledMethod's literal frame.
            # This, in turn, indicates where the 
            # CompiledMethod's bytecodes start. 
            index0 = index0 - self.getliteralsize() - self.headersize()
            assert index0 < len(self.bytes)
            return space.wrap_int(ord(self.bytes[index0]))
        
    def atput0(self, space, index0, w_value):
        if index0 <= self.getliteralsize():
            self.literalatput0(space, index0 / constants.BYTES_PER_WORD, w_value)
        else:
            # XXX use to-be-written unwrap_char
            index0 = index0 - self.getliteralsize() - self.headersize()
            assert index0 < len(self.bytes)
            self.setchar(index0, chr(space.unwrap_int(w_value)))

    def setchar(self, index0, character):
        assert index0 >= 0
        self.bytes[index0] = character

# Use black magic to create w_nil without running the constructor,
# thus allowing it to be used even in the constructor of its own
# class.  Note that we patch its class in the space
# YYY there should be no global w_nil
w_nil = instantiate(W_PointersObject)
w_nil._vars = []
