import os

from spyvm import constants, model, shadow, wrapper
from spyvm.error import UnwrappingError, WrappingError, PrimitiveFailedError
from rpython.rlib import jit, rpath
from rpython.rlib.objectmodel import instantiate, specialize
from rpython.rlib.rarithmetic import intmask, r_uint, int_between

class ObjSpace(object):
    def __init__(self):
        self.classtable = {}
        self._executable_path = [""] # XXX: we cannot set the attribute
                                  # directly on the frozen objectspace
        self.make_bootstrap_classes()
        self.make_bootstrap_objects()

    def find_executable(self, executable):
        if os.sep in executable or (os.name == "nt" and ":" in executable):
            return executable
        path = os.environ.get("PATH")
        if path:
            for dir in path.split(os.pathsep):
                f = os.path.join(dir, executable)
                if os.path.isfile(f):
                    executable = f
                    break
        return rpath.rabspath(executable)

    def runtime_setup(self, executable):
        fullpath = rpath.rabspath(self.find_executable(executable))
        i = fullpath.rfind(os.path.sep) + 1
        assert i > 0
        self._executable_path[0] = fullpath[:i]

    def executable_path(self):
        return self._executable_path[0]

    def make_bootstrap_classes(self):
        def define_core_cls(name, w_superclass, w_metaclass):
            assert name.startswith('w_')
            w_class = bootstrap_class(self, instsize=0,    # XXX
                                      w_superclass=w_superclass,
                                      w_metaclass=w_metaclass,
                                      name=name[2:])
            self.classtable[name] = w_class
            return w_class

        #   A complete minimal setup (including Behavior) would look like this
        #
        #   class:              superclass:         metaclass:
        #   ------------------- ------------------- -------------------
        #   Object              *nil                 Object class
        #   Behavior            Object              Behavior class
        #   ClassDescription    Behavior            ClassDescription class
        #   Class               ClassDescription    Class class
        #   Metaclass           ClassDescription    Metaclass class
        #   Object class        *Class              *Metaclass
        #   Behavior class      Object class        *Metaclass
        #   ClassDescription cl Behavior class      *Metaclass
        #   Class class         ClassDescription cl *Metaclass
        #   Metaclass class     ClassDescription cl *Metaclass

        #    Class Name            Super class name
        cls_nm_tbl = [
            ["w_Object",           "w_ProtoObject"], # there is not ProtoObject in mini.image
            ["w_Behavior",         "w_Object"],
            ["w_ClassDescription", "w_Behavior"],
            ["w_Class",            "w_ClassDescription"],
            ["w_Metaclass",        "w_ClassDescription"],
            ]
        define_core_cls("w_ProtoObjectClass", None, None)
        w_ProtoObjectClass = self.classtable["w_ProtoObjectClass"]
        define_core_cls("w_ProtoObject", None, w_ProtoObjectClass)
        for (cls_nm, super_cls_nm) in cls_nm_tbl:
            meta_nm = cls_nm + "Class"
            meta_super_nm = super_cls_nm + "Class"
            w_metacls = define_core_cls(meta_nm, self.classtable[meta_super_nm], None)
            define_core_cls(cls_nm, self.classtable[super_cls_nm], w_metacls)
        w_Class = self.classtable["w_Class"]
        s_Metaclass = self.classtable["w_Metaclass"].as_class_get_penumbra(self)
        # XXX
        proto_shadow = w_ProtoObjectClass._shadow
        proto_shadow.store_w_superclass(w_Class)
        # at this point, all classes that still lack a w_class are themselves
        # metaclasses
        for nm, w_cls_obj in self.classtable.items():
            if w_cls_obj.s_class is None:
                w_cls_obj.s_class = s_Metaclass

        def define_cls(cls_nm, supercls_nm, instvarsize=0, format=shadow.POINTERS,
                       varsized=False):
            assert cls_nm.startswith("w_")
            meta_nm = cls_nm + "Class"
            meta_super_nm = supercls_nm + "Class"
            w_Metaclass = self.classtable["w_Metaclass"]
            w_meta_cls = self.classtable[meta_nm] = \
                         bootstrap_class(self, 0,   # XXX
                                         self.classtable[meta_super_nm],
                                         w_Metaclass,
                                         name=meta_nm[2:])
            w_cls = self.classtable[cls_nm] = \
                         bootstrap_class(self, instvarsize,
                                         self.classtable[supercls_nm],
                                         w_meta_cls,
                                         format=format,
                                         varsized=varsized,
                                         name=cls_nm[2:])

        define_cls("w_Magnitude", "w_Object")
        define_cls("w_Character", "w_Magnitude", instvarsize=1)
        define_cls("w_Number", "w_Magnitude")
        define_cls("w_Integer", "w_Number")
        define_cls("w_SmallInteger", "w_Integer")
        define_cls("w_LargePositiveInteger", "w_Integer", format=shadow.BYTES)
        define_cls("w_Float", "w_Number", format=shadow.BYTES)
        define_cls("w_Message", "w_Object")
        define_cls("w_Collection", "w_Object")
        define_cls("w_SequenceableCollection", "w_Collection")
        define_cls("w_ArrayedCollection", "w_SequenceableCollection")
        define_cls("w_Array", "w_ArrayedCollection", varsized=True)
        define_cls("w_String", "w_ArrayedCollection", format=shadow.BYTES)
        define_cls("w_Bitmap", "w_ArrayedCollection", varsized=True, format=shadow.WORDS)
        define_cls("w_UndefinedObject", "w_Object")
        define_cls("w_Boolean", "w_Object")
        define_cls("w_True", "w_Boolean")
        define_cls("w_False", "w_Boolean")
        define_cls("w_ByteArray", "w_ArrayedCollection", format=shadow.BYTES)
        define_cls("w_MethodDict", "w_Object", instvarsize=2, varsized=True)
        define_cls("w_CompiledMethod", "w_ByteArray", format=shadow.COMPILED_METHOD)
        define_cls("w_ContextPart", "w_Object")
        define_cls("w_MethodContext", "w_ContextPart")
        define_cls("w_Link", "w_Object")
        define_cls("w_Process", "w_Link")
        define_cls("w_Point", "w_Object")
        define_cls("w_LinkedList", "w_SequenceableCollection")
        define_cls("w_Semaphore", "w_LinkedList")
        define_cls("w_BlockContext", "w_ContextPart",
                   instvarsize=constants.BLKCTX_STACK_START)
        define_cls("w_BlockClosure", "w_Object",
                   instvarsize=constants.BLKCLSR_SIZE,
                   varsized=True)
        # make better accessors for classes that can be found in special object
        # table
        for name in constants.classes_in_special_object_table.keys():
            name = 'w_' + name
            setattr(self, name, self.classtable.get(name))

    def make_bootstrap_objects(self):
        def bld_char(i):
            w_cinst = self.w_Character.as_class_get_shadow(self).new()
            w_cinst.store(self, constants.CHARACTER_VALUE_INDEX,
                          model.W_SmallInteger(i))
            return w_cinst
        w_charactertable = model.W_PointersObject(self,
            self.classtable['w_Array'], 256)
        self.w_charactertable = w_charactertable
        for i in range(256):
            self.w_charactertable.atput0(self, i, bld_char(i))


        # Very special nil hack: in order to allow W_PointersObject's to
        # initialize their fields to nil, we have to create it in the model
        # package, and then patch up its fields here:
        def patch_nil(w_nil):
            from spyvm.fieldtypes import nilTyper
            w_nil.space = self
            w_nil.fieldtypes = nilTyper
            w_nil.s_class = self.classtable['w_UndefinedObject'].as_class_get_penumbra(self)
            return w_nil
        w_nil = self.w_nil = patch_nil(model.w_nil)

        w_true = self.classtable['w_True'].as_class_get_shadow(self).new()
        self.w_true = w_true
        w_false = self.classtable['w_False'].as_class_get_shadow(self).new()
        self.w_false = w_false
        self.w_minus_one = model.W_SmallInteger(-1)
        self.w_zero = model.W_SmallInteger(0)
        self.w_one = model.W_SmallInteger(1)
        self.w_two = model.W_SmallInteger(2)
        w_special_selectors = model.W_PointersObject(self,
            self.classtable['w_Array'], len(constants.SPECIAL_SELECTORS) * 2)
        self.w_special_selectors = w_special_selectors

        self.objtable = {}
        for name in constants.objects_in_special_object_table:
            name = "w_" + name
            try:
                self.objtable[name] = locals()[name]
            except KeyError, e:
                self.objtable[name] = None

    @specialize.arg(1)
    def get_special_selector(self, selector):
        i0 = constants.find_selectorindex(selector)
        self.w_special_selectors.as_cached_object_get_shadow(self)
        return self.w_special_selectors.fetch(self, i0)

    # methods for wrapping and unwrapping stuff

    def wrap_int(self, val):
        from spyvm import constants
        assert isinstance(val, int)
        # we don't do tagging
        return model.W_SmallInteger(val)

    def wrap_uint(self, val):
        from rpython.rlib.objectmodel import we_are_translated
        if val < 0:
            raise WrappingError("negative integer")
        else:
            return self.wrap_positive_32bit_int(intmask(val))

    def wrap_positive_32bit_int(self, val):
        # This will always return a positive value.
        # XXX: For now, we assume that val is at most 32bit, i.e. overflows are
        # checked for before wrapping. Also, we ignore tagging.
        if int_between(0, val, constants.MAXINT):
            return model.W_SmallInteger(val)
        else:
            return model.W_LargePositiveInteger1Word(val)

    def wrap_float(self, i):
        return model.W_Float(i)

    def wrap_string(self, string):
        w_inst = self.w_String.as_class_get_shadow(self).new(len(string))
        for i in range(len(string)):
            w_inst.setchar(i, string[i])
        return w_inst

    def wrap_char(self, c):
        return self.w_charactertable.fetch(self, ord(c))

    def wrap_bool(self, b):
        if b:
            return self.w_true
        else:
            return self.w_false

    def wrap_list(self, lst_w):
        """
        Converts a Python list of wrapped objects into
        a wrapped smalltalk array
        """
        lstlen = len(lst_w)
        res = self.w_Array.as_class_get_shadow(self).new(lstlen)
        for i in range(lstlen):
            res.atput0(self, i, lst_w[i])
        return res

    def unwrap_int(self, w_value):
        if isinstance(w_value, model.W_SmallInteger):
            return intmask(w_value.value)
        elif isinstance(w_value, model.W_LargePositiveInteger1Word):
            if w_value.value >= 0:
                return intmask(w_value.value)
            else:
                raise UnwrappingError("The value is negative when interpreted as 32bit value.")
        raise UnwrappingError("expected a W_SmallInteger or W_LargePositiveInteger1Word, got %s" % (w_value,))

    def unwrap_uint(self, w_value):
        return w_value.unwrap_uint(self)

    def unwrap_positive_32bit_int(self, w_value):
        if isinstance(w_value, model.W_SmallInteger):
            if w_value.value >= 0:
                return r_uint(w_value.value)
        elif isinstance(w_value, model.W_LargePositiveInteger1Word):
            return r_uint(w_value.value)
        raise UnwrappingError("Wrong types or negative SmallInteger.")

    def unwrap_char(self, w_char):
        from spyvm import constants
        w_class = w_char.getclass(self)
        if not w_class.is_same_object(self.w_Character):
            raise UnwrappingError("expected character, got %s" % (w_class, ))
        w_ord = w_char.fetch(self, constants.CHARACTER_VALUE_INDEX)
        w_class = w_ord.getclass(self)
        if not w_class.is_same_object(self.w_SmallInteger):
            raise UnwrappingError("expected smallint from character, got %s" % (w_class, ))

        assert isinstance(w_ord, model.W_SmallInteger)
        return chr(w_ord.value)

    def unwrap_float(self, w_v):
        from spyvm import model
        if isinstance(w_v, model.W_Float): return w_v.value
        elif isinstance(w_v, model.W_SmallInteger): return float(w_v.value)
        raise UnwrappingError()

    def unwrap_pointersobject(self, w_v):
        if not isinstance(w_v, model.W_PointersObject):
            raise UnwrappingError()
        return w_v

    @jit.look_inside_iff(lambda self, w_array: jit.isconstant(w_array.size()))
    def unwrap_array(self, w_array):
        # Check that our argument has pointers format and the class:
        if not w_array.getclass(self).is_same_object(self.w_Array):
            raise UnwrappingError()
        assert isinstance(w_array, model.W_PointersObject)

        return [w_array.at0(self, i) for i in range(w_array.size())]

    def get_display(self):
        w_display = self.objtable['w_display']
        if w_display:
            w_bitmap = w_display.fetch(self, 0)
            if isinstance(w_bitmap, model.W_DisplayBitmap):
                return w_bitmap.display
        raise PrimitiveFailedError("No display")

    def _freeze_(self):
        return True

    def newClosure(self, w_outer_ctxt, pc, numArgs, copiedValues):
        assert isinstance(w_outer_ctxt, model.W_PointersObject)
        pc_with_bytecodeoffset = pc + w_outer_ctxt.as_context_get_shadow(self).s_method().bytecodeoffset + 1
        BlockClosureShadow = self.w_BlockClosure.as_class_get_shadow(self)
        numCopied = len(copiedValues)
        w_closure = BlockClosureShadow.new(numCopied)
        closure = wrapper.BlockClosureWrapper(self, w_closure)
        closure.store_outerContext(w_outer_ctxt)
        closure.store_startpc(pc_with_bytecodeoffset)
        closure.store_numArgs(numArgs)
        for i0 in range(numCopied):
            closure.atput0(i0, copiedValues[i0])
        return w_closure


def bootstrap_class(space, instsize, w_superclass=None, w_metaclass=None,
                    name='?', format=shadow.POINTERS, varsized=False):
    from spyvm import model
    w_class = model.W_PointersObject(space, w_metaclass, 0)
                                             # a dummy placeholder for testing
    # XXX
    s = instantiate(shadow.ClassShadow)
    s.space = space
    s.version = shadow.Version()
    s._w_self = w_class
    s.subclass_s = {}
    s._s_superclass = None
    s.store_w_superclass(w_superclass)
    s.name = name
    s._instance_size = instsize
    s.instance_kind = format
    s._s_methoddict = None
    s.instance_varsized = varsized or format != shadow.POINTERS
    w_class.store_shadow(s)
    return w_class
