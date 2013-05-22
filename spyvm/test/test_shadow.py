import random
from spyvm import model, shadow, constants, interpreter
from spyvm import objspace

space = objspace.ObjSpace()

w_Object = space.classtable['w_Object']
w_Metaclass  = space.classtable['w_Metaclass']
w_MethodDict = space.classtable['w_MethodDict']
w_Array      = space.classtable['w_Array']

def build_methoddict(methods):
    size = int(len(methods) * 1.5)
    w_methoddict = w_MethodDict.as_class_get_shadow(space).new(size)
    w_array = w_Array.as_class_get_shadow(space).new(size)
    for i in range(size):
        w_array.store(space, i, space.w_nil)
        w_methoddict.store(space, constants.METHODDICT_NAMES_INDEX+i, space.w_nil)
    w_tally = space.wrap_int(len(methods))
    w_methoddict.store(space, constants.METHODDICT_TALLY_INDEX, w_tally)
    w_methoddict.store(space, constants.METHODDICT_VALUES_INDEX, w_array)
    positions = range(size)
    random.shuffle(positions)
    for selector, w_compiledmethod in methods.items():
        pos = positions.pop()
        w_selector = space.wrap_string(selector)
        w_methoddict.store(space, constants.METHODDICT_NAMES_INDEX+pos, w_selector)
        w_array.store(space, pos, w_compiledmethod)
    return w_methoddict

def build_smalltalk_class(name, format, w_superclass=w_Object,
                          w_classofclass=None, methods={}):
    if w_classofclass is None:
        w_classofclass = build_smalltalk_class(None, 0x94,
                                               w_superclass.getclass(space),
                                               w_Metaclass)
    w_methoddict = build_methoddict(methods)
    size = constants.CLASS_NAME_INDEX + 1
    w_class = model.W_PointersObject(space, w_classofclass, size)
    w_class.store(space, constants.CLASS_SUPERCLASS_INDEX, w_superclass)
    w_class.store(space, constants.CLASS_METHODDICT_INDEX, w_methoddict)
    w_class.store(space, constants.CLASS_FORMAT_INDEX, space.wrap_int(format))
    if name is not None:
        w_class.store(space, constants.CLASS_NAME_INDEX, space.wrap_string(name))
    w_class.as_class_get_shadow(space).s_methoddict().sync_cache()
    return w_class

def basicshape(name, format, kind, varsized, instsize):
    w_class = build_smalltalk_class(name, format)
    classshadow = w_class.as_class_get_shadow(space)
    assert classshadow.instance_kind == kind
    assert classshadow.isvariable() == varsized
    assert classshadow.instsize() == instsize
    assert classshadow.name == name
    assert classshadow.s_superclass() is w_Object.as_class_get_shadow(space)

def test_basic_shape():
    yield basicshape, "Empty",        0x02,    shadow.POINTERS, False, 0
    yield basicshape, "Seven",        0x90,    shadow.POINTERS, False, 7
    yield basicshape, "Seventyseven", 0x1009C, shadow.POINTERS, False, 77
    yield basicshape, "EmptyVar",     0x102,   shadow.POINTERS, True,  0
    yield basicshape, "VarTwo",       0x3986,  shadow.POINTERS, True,  2
    yield basicshape, "VarSeven",     0x190,   shadow.POINTERS, True,  7
    yield basicshape, "Bytes",        0x402,   shadow.BYTES,    True,  0
    yield basicshape, "Words",        0x302,   shadow.WORDS,    True,  0
    yield basicshape, "CompiledMeth", 0xE02,   shadow.COMPILED_METHOD, True, 0

def test_methoddict():
    methods = {'foo': model.W_CompiledMethod(0),
               'bar': model.W_CompiledMethod(0)}
    w_class = build_smalltalk_class("Demo", 0x90, methods=methods)
    classshadow = w_class.as_class_get_shadow(space)
    methoddict = classshadow.s_methoddict().methoddict
    assert len(methods) == len(methoddict)
    for w_key, value in methoddict.items():
        assert methods[w_key.as_string()].as_compiledmethod_get_shadow(space) is value

def method(tempsize=3,argsize=2, bytes="abcde"):
    w_m = model.W_CompiledMethod()
    w_m.bytes = bytes
    w_m.tempsize = tempsize
    w_m.argsize = argsize
    w_m.literalsize = 2
    return w_m

def methodcontext(w_sender=space.w_nil, pc=13, stackpointer=0, stacksize=5,
                  method=method()):
    w_object = model.W_PointersObject(space, space.w_MethodContext, constants.MTHDCTX_TEMP_FRAME_START+method.tempsize+stacksize)
    w_object.store(space, constants.CTXPART_SENDER_INDEX, w_sender)
    w_object.store(space, constants.CTXPART_PC_INDEX, space.wrap_int(pc))
    w_object.store(space, constants.CTXPART_STACKP_INDEX, space.wrap_int(method.tempsize+stackpointer))
    w_object.store(space, constants.MTHDCTX_METHOD, method)
    # XXX
    w_object.store(space, constants.MTHDCTX_CLOSURE_OR_NIL, space.w_nil)
    w_object.store(space, constants.MTHDCTX_RECEIVER, space.wrap_string('receiver'))

    w_object.store(space, constants.MTHDCTX_TEMP_FRAME_START, space.wrap_string('el'))
    return w_object

def blockcontext(w_sender=space.w_nil, pc=13, stackpointer=1, stacksize=5,
                  home=methodcontext()):
    w_object = model.W_PointersObject(space, space.w_MethodContext, constants.MTHDCTX_TEMP_FRAME_START+stacksize)
    w_object.store(space, constants.CTXPART_SENDER_INDEX, w_sender)
    w_object.store(space, constants.CTXPART_PC_INDEX, space.wrap_int(pc))
    w_object.store(space, constants.CTXPART_STACKP_INDEX, space.wrap_int(stackpointer))
    w_object.store(space, constants.BLKCTX_BLOCK_ARGUMENT_COUNT_INDEX, space.wrap_int(54))
    w_object.store(space, constants.BLKCTX_INITIAL_IP_INDEX, space.wrap_int(17))
    w_object.store(space, constants.BLKCTX_HOME_INDEX, home)
    w_object.store(space, constants.BLKCTX_STACK_START, space.wrap_string('el'))
    return w_object

def test_context():
    w_m = method()
    w_object = methodcontext(stackpointer=3, method=w_m)
    w_object2 = methodcontext(w_sender=w_object)
    s_object = w_object.as_methodcontext_get_shadow(space)
    assert len(s_object.stack()) == 3
    s_object2 = w_object2.as_methodcontext_get_shadow(space)
    assert w_object2.fetch(space, constants.CTXPART_SENDER_INDEX) == w_object
    assert s_object.w_self() == w_object
    assert s_object2.w_self() == w_object2
    assert s_object.s_sender() == None
    assert s_object2.s_sender() == s_object
    assert s_object.w_receiver().as_string() == 'receiver'
    s_object2.settemp(0, 'a')
    s_object2.settemp(1, 'b')
    assert s_object2.gettemp(1) == 'b'
    assert s_object2.gettemp(0) == 'a'
    assert s_object.w_method() == w_m
    idx = s_object.stackstart() + s_object.tempsize()
    w_object.store(space, idx, space.wrap_string('f'))
    w_object.store(space, idx + 1, space.wrap_string('g'))
    w_object.store(space, idx + 2, space.wrap_string('h'))
    assert map(lambda x: x.as_string(), s_object.stack()) == ['f', 'g', 'h' ]
    assert s_object.top().as_string() == 'h'
    s_object.push('i')
    assert s_object.top() == 'i'
    assert s_object.peek(1).as_string() == 'h'
    assert s_object.pop() == 'i'
    assert map(lambda x: x.as_string(), s_object.pop_and_return_n(2)) == ['g', 'h']
    assert s_object.pop().as_string() == 'f'
    assert s_object.external_stackpointer() == s_object.stackstart() + s_object.tempsize()
    assert s_object.stackdepth() == s_object.tempsize()

def test_methodcontext():
    w_m = method()
                              # Point over 2 literals of size 4
    w_object = methodcontext(pc=13,method=w_m)
    s_object = w_object.as_methodcontext_get_shadow(space)
    assert s_object.getbytecode() == 97
    assert s_object.getbytecode() == 98
    assert s_object.getbytecode() == 99
    assert s_object.getbytecode() == 100
    assert s_object.getbytecode() == 101
    assert s_object.s_home() == s_object

def test_attach_mc():
    w_m = method()
    w_object = methodcontext(pc=13, method=w_m)
    old_vars = w_object._vars
    s_object = w_object.as_methodcontext_get_shadow(space)
    assert w_object._vars is None

def test_attach_bc():
    w_object = blockcontext(pc=13)
    old_vars = w_object._vars
    s_object = w_object.as_blockcontext_get_shadow(space)
    assert w_object._vars is None

def test_replace_to_bc():
    w_object = blockcontext(pc=13)
    old_vars = w_object._vars
    s_object = w_object.as_blockcontext_get_shadow(space)
    s_object._shadow = None
    s_newobject = w_object.as_blockcontext_get_shadow(space)
    assert ([s_newobject.fetch(i) for i in range(s_newobject.size())] ==
            [s_object.fetch(i) for i in range(s_newobject.size())])
    assert w_object._shadow is s_newobject

def test_compiledmethodshadow():
    from test_model import joinbits
    header = joinbits([0,2,0,1,0,0],[9,8,1,6,4,1])

    w_compiledmethod = model.W_CompiledMethod(3, header)
    w_compiledmethod.setbytes(list("abc"))
    shadow = w_compiledmethod.as_compiledmethod_get_shadow(space)
    assert shadow.bytecode == "abc"
    assert shadow.bytecodeoffset == 12
    assert shadow.literalsize == 8 # 12 - 4byte header
    assert shadow.tempsize() == 1

    w_compiledmethod.literalatput0(space, 1, 17)
    w_compiledmethod.literalatput0(space, 2, 41)
    assert w_compiledmethod._shadow is not None
    assert shadow.literals == [17, 41]

    w_compiledmethod.atput0(space, 14, space.wrap_int(ord("x")))

    assert shadow.bytecode == "abx"
    assert shadow is w_compiledmethod.as_compiledmethod_get_shadow(space)

def test_cached_object_shadow():
    w_o = space.wrap_list([0, 1, 2, 3, 4, 5, 6, 7])
    s_o = w_o.as_cached_object_get_shadow(space)
    version = s_o.version
    for i in range(w_o.size()):
        assert w_o.at0(space, i) == i
    w_o.atput0(space, 0, 8)
    assert version is not s_o.version
    assert w_o.at0(space, 0) == 8

def test_observee_shadow():
    notified = False
    class Observer():
        def __init__(self): self.notified = False
        def update(self): self.notified = True
    o = Observer()
    w_o = w_Array.as_class_get_shadow(space).new(1)
    w_o.as_observed_get_shadow(space).notify(o)
    assert not o.notified
    w_o.store(space, 0, 1)
    assert o.notified
    assert w_o.fetch(space, 0) == 1
    try:
        w_o._shadow.notify(Observer())
    except RuntimeError:
        pass
    else:
        assert False

def test_cached_methoddict():
    # create a methoddict
    foo = model.W_CompiledMethod(0)
    bar = model.W_CompiledMethod(0)
    baz = model.W_CompiledMethod(0)
    methods = {'foo': foo,
               'bar': bar}
    w_class = build_smalltalk_class("Demo", 0x90, methods=methods)
    s_class = w_class.as_class_get_shadow(space)
    s_methoddict = s_class.s_methoddict()
    s_methoddict.sync_cache()
    i = 0
    key = s_methoddict.w_self()._fetch(constants.METHODDICT_NAMES_INDEX+i)
    while key is space.w_nil:
        i = i + 1
        key = s_methoddict.w_self()._fetch(constants.METHODDICT_NAMES_INDEX+i)

    assert (s_class.lookup(key) is foo.as_compiledmethod_get_shadow(space)
            or s_class.lookup(key) is bar.as_compiledmethod_get_shadow(space))
    # change that entry
    w_array = s_class.w_methoddict()._fetch(constants.METHODDICT_VALUES_INDEX)
    version = s_class.version
    w_array.atput0(space, i, baz)

    assert s_class.lookup(key) is baz.as_compiledmethod_get_shadow(space)
    assert version is not s_class.version

def test_updating_class_changes_subclasses():
    w_parent = build_smalltalk_class("Demo", 0x90,
            methods={'bar': model.W_CompiledMethod(0)})
    w_class = build_smalltalk_class("Demo", 0x90,
            methods={'foo': model.W_CompiledMethod(0)}, w_superclass=w_parent)
    s_class = w_class.as_class_get_shadow(space)
    version = s_class.version

    w_method = model.W_CompiledMethod(0)
    key = space.wrap_string('foo')

    s_md = w_parent.as_class_get_shadow(space).s_methoddict()
    s_md.sync_cache()
    w_ary = s_md._w_self._fetch(constants.METHODDICT_VALUES_INDEX)
    s_md._w_self.atput0(space, 0, key)
    w_ary.atput0(space, 0, w_method)

    assert s_class.lookup(key) is w_method.as_compiledmethod_get_shadow(space)
    assert s_class.version is not version
    assert s_class.version is w_parent.as_class_get_shadow(space).version

def test_returned_contexts_pc():
    w_context = methodcontext()
    s_context = w_context.as_methodcontext_get_shadow(space)
    assert w_context.fetch(space, constants.CTXPART_PC_INDEX) is not space.w_nil
    s_context.mark_returned()
    assert w_context.fetch(space, constants.CTXPART_PC_INDEX) is space.w_nil
