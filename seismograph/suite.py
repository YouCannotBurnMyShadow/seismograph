# -*- coding: utf-8 -*-

import traceback
from types import FunctionType

from . import case
from . import loader
from . import runnable
from .utils import pyv
from . import extensions
from .utils.common import measure_time
from .utils.common import call_to_chain
from .groups.default import DefaultCaseGroup
from .exceptions import ExtensionNotRequired
from .exceptions import ALLOW_RAISED_EXCEPTIONS


DEFAULT_LAYERS = []
MATCH_SUITE_TO_LAYER = {}


def with_match_layers(context, suite):
    for layer in context.layers:
        yield layer

    for cls, layer in MATCH_SUITE_TO_LAYER.items():
        if isinstance(suite, cls) and layer.enabled:
            yield layer


class MountData(object):

    def __init__(self, config=None):
        self.__config = config

    @property
    def config(self):
        return self.__config


class BuildRule(object):

    def __init__(self, suite_name, case_name=None, test_name=None):
        self.__suite_name = suite_name
        self.__case_name = case_name
        self.__test_name = test_name

    def __str__(self):
        if self.__suite_name and self.__case_name and self.__test_name:
            return '{}:{}.{}'.format(
                self.__suite_name, self.__case_name, self.__case_name,
            )

        if self.__suite_name and self.__case_name:
            return '{}:{}'.format(
                self.__suite_name, self.__case_name,
            )

        return self.__suite_name

    def __repr__(self):
        return '<{}(suite_name={}, case_name={}, test_name={})>'.format(
            self.__class__.__name__,
            self.__suite_name,
            self.__case_name,
            self.__test_name,
        )

    @property
    def suite_name(self):
        return self.__suite_name

    @property
    def case_name(self):
        return self.__case_name

    @property
    def test_name(self):
        return self.__test_name

    def is_of(self, suite):
        return self.__suite_name == suite.name


class SuiteLayer(runnable.LayerOfRunnableObject):

    def on_init(self, suite):
        """
        :type suite: Suite
        """
        pass

    def on_require(self, require):
        """
        :type require: list
        """
        pass

    def on_build_rule(self, build_rules):
        """
        :type build_rules: list
        """
        pass

    def on_setup(self, suite):
        """
        :type suite: Suite
        """
        pass

    def on_teardown(self, suite):
        """
        :type suite: Suite
        """
        pass

    def on_mount(self, suite, program):
        """
        :type suite: Suite
        :type program: seismograph.program.Program
        """
        pass

    def on_run(self, suite):
        """
        :type suite: Suite
        """
        pass

    def on_error(self, error, suite, result):
        """
        :type error: BaseException
        :type suite: Suite
        :type result: seismograph.result.Result
        """
        pass


class SuiteContext(runnable.ContextOfRunnableObject):

    def __init__(self, setup, teardown):
        self.__layers = []
        self.__require = []

        self.__extensions = {}
        self.__build_rules = []

        self.__setup_callbacks = [setup]
        self.__teardown_callbacks = [teardown]

    @property
    def require(self):
        return self.__require

    @property
    def extensions(self):
        return self.__extensions

    @property
    def build_rules(self):
        return self.__build_rules

    @property
    def setup_callbacks(self):
        return self.__setup_callbacks

    @property
    def teardown_callbacks(self):
        return self.__teardown_callbacks

    @property
    def layers(self):
        for layer in DEFAULT_LAYERS:
            if layer.enabled:
                yield layer

        for layer in self.__layers:
            if layer.enabled:
                yield layer

    def add_layers(self, layers):
        self.__layers.extend(layers)

    def install_extensions(self):
        for ext_name in self.__require:
            if ext_name not in self.__extensions:
                self.__extensions[ext_name] = extensions.get(ext_name)

    def start_context(self, suite):
        try:
            call_to_chain(self.__setup_callbacks, None)
            call_to_chain(
                with_match_layers(self, suite), 'on_setup', suite,
            )
        except BaseException:
            runnable.stopped_on(suite, 'start_context')
            raise

    def stop_context(self, suite):
        try:
            call_to_chain(self.__teardown_callbacks, None)
            call_to_chain(
                with_match_layers(self, suite), 'on_teardown', suite,
            )
        except BaseException:
            runnable.stopped_on(suite, 'stop_context')
            raise

    def on_init(self, suite):
        call_to_chain(
            with_match_layers(self, suite), 'on_init', suite,
        )

    def on_require(self, suite):
        call_to_chain(
            with_match_layers(self, suite), 'on_require', self.__require,
        )

    def on_build_rule(self, suite):
        call_to_chain(
            with_match_layers(self, suite), 'on_build_rule', self.__build_rules,
        )

    def on_mount(self, suite, program):
        call_to_chain(
            with_match_layers(self, suite), 'on_mount', suite, program,
        )

    def on_run(self, suite):
        try:
            call_to_chain(
                with_match_layers(self, suite), 'on_run', suite,
            )
        except BaseException:
            runnable.stopped_on(suite, 'on_run')
            raise

    def on_error(self, error, suite, result):
        try:
            call_to_chain(
                with_match_layers(self, suite), 'on_error', error, suite, result,
            )
        except BaseException:
            runnable.stopped_on(suite, 'on_error')
            raise


class Suite(runnable.RunnableObject, runnable.MountObjectMixin, runnable.BuildObjectMixin):

    __layers__ = None
    __require__ = None
    __create_reason__ = False
    __case_class__ = case.Case
    __case_group_class__ = None

    #
    # Base components of runnable object
    #

    def __is_run__(self):
        return self.__is_run

    def __is_build__(self):
        return self.__is_build

    def __is_mount__(self):
        return isinstance(self.__mount_data__, MountData)

    def __class_name__(self):
        return self.__name

    #
    # Behavior on magic methods
    #

    def __iter__(self):
        return iter(self.__case_instances)

    def __nonzero__(self):
        return bool(self.__case_instances)

    def __bool__(self):  # please python 3
        return self.__nonzero__()

    #
    # Self code is starting here
    #

    def __init__(self, name, require=None, layers=None):
        super(Suite, self).__init__()

        self.__name = name

        self.__is_run = False
        self.__is_build = False

        self.__case_classes = []
        self.__case_instances = []

        self.__mount_data__ = None

        self.__context = SuiteContext(self.setup, self.teardown)

        if layers:
            self.__context.add_layers(layers)

        if self.__layers__:
            self.__context.add_layers(self.__layers__)

        if require:
            self.__context.require.extend(require)

        if self.__require__:
            self.__context.require.extend(self.__require__)

        self.__context.on_init(self)
        self.__context.on_require(self)
        self.__context.on_build_rule(self)

    def __build__(self, case_name=None, test_name=None):
        if case_name:
            cls = loader.load_case_from_suite(
                case_name, self,
            )

            self.__case_instances.extend(
                loader.load_tests_from_case(
                    cls,
                    config=self.config,
                    method_name=test_name,
                    box_class=case.CaseBox,
                    extensions=self.__context.extensions,
                ),
            )
        else:
            for cls in self.__case_classes:
                self.__case_instances.extend(
                    loader.load_tests_from_case(
                        cls,
                        config=self.config,
                        box_class=case.CaseBox,
                        extensions=self.__context.extensions,
                    ),
                )

    @property
    def name(self):
        return self.__name

    @property
    @runnable.mount_method
    def config(self):
        return self.__mount_data__.config

    @property
    def cases(self):
        return self.__case_classes

    @property
    def context(self):
        return self.__context

    def _make_group(self):
        if self.__case_group_class__:
            return self.__case_group_class__(
                self.__case_instances, self.config,
            )

        if self.config.GEVENT:
            pyv.check_gevent_supported()

            from .groups.gevent import GeventCaseGroup

            return GeventCaseGroup(
                self.__case_instances, self.config,
            )

        if self.config.THREADING or self.config.MULTIPROCESSING:
            from .groups.threading import ThreadingCaseGroup

            return ThreadingCaseGroup(
                self.__case_instances, self.config,
            )

        return DefaultCaseGroup(
            self.__case_instances, self.config,
        )

    def setup(self):
        pass

    def teardown(self):
        pass

    def add_setup(self, f):
        self.__context.setup_callbacks.append(f)
        return f

    def add_teardown(self, f):
        self.__context.teardown_callbacks.append(f)
        return f

    def assign_build_rule(self, rule):
        """
        :type rule: BuildRule
        """
        assert rule.is_of(self), 'Build rule is not of this suite {}'.format(
            str(rule),
        )

        if rule.case_name:
            self.__context.build_rules.append(rule)

    @runnable.build_method
    def ext(self, name):
        if name not in self.__context.require:
            raise ExtensionNotRequired(name)

        return self.__context.extensions.get(name)

    def mount_to(self, program):
        if runnable.is_mount(self):
            raise RuntimeError(
                'Suite "{}" already mount'.format(self.__name),
            )

        program.suites.append(self)

        self.__mount_data__ = MountData(
            config=program.config,
        )

        self.__context.on_mount(self, program)

    def get_map(self):
        mp = {}

        for case_class in self.__case_classes:
            mp[case_class.__name__] = {
                'cls': case_class,
                'tests': dict(
                    (atr, getattr(case_class, atr))
                    for atr in dir(case_class)
                    if atr.startswith(loader.TEST_NAME_PREFIX)
                    or
                    atr == loader.DEFAULT_TEST_NAME,
                ),
            }

        return mp

    def register(self, cls=None, **kwargs):
        if not cls and not kwargs:
            raise TypeError('cls param or **kwargs is required')
        elif cls and kwargs:
            raise TypeError('**kwargs can not be used with cls param')

        def wrapped(
                _class,
                skip=None,
                flows=None,
                static=False,
                require=None,
                always_success=False,
                assertion_class=None):
            if type(_class) == FunctionType:
                _class = case.make_case_class_from_function(
                    _class,
                    static=static,
                    base_class=self.__case_class__,
                )

            if skip:
                case.skip(skip)(_class)

            if flows:
                setattr(_class, '__flows__', flows)

            if always_success:
                setattr(_class, '__always_success__', True)

            if assertion_class:
                setattr(_class, '__assertion_class__', assertion_class)

            self.__case_classes.append(
                _class.mount_to(
                    self,
                    require=require,
                ),
            )

            return _class

        if cls:
            return wrapped(cls)

        def wrapper(_class):
            return wrapped(_class, **kwargs)

        return wrapper

    @runnable.mount_method
    def build(self, case_name=None, test_name=None, shuffle=None):
        if self.__is_build:
            raise RuntimeError(
                'Suite "{}" is already built'.format(
                    self.__class__.__name__,
                ),
            )

        self.__context.install_extensions()

        if self.__context.build_rules and not case_name:
            for rule in self.__context.build_rules:
                self.__build__(
                    case_name=rule.case_name,
                    test_name=rule.test_name,
                )
        else:
            self.__build__(
                case_name=case_name,
                test_name=test_name,
            )

        if shuffle:
            shuffle(self.__case_instances)

        self.__is_build = True

    @runnable.build_method
    def run(self, result):
        self.__is_run = True

        if result.current_state.should_stop or not self.__case_instances:
            return

        group = self._make_group()
        timer = measure_time()

        with result.proxy(self) as result_proxy:
            try:
                self.__context.on_run(self)

                with self.__context(self):
                    group(result_proxy)
            except ALLOW_RAISED_EXCEPTIONS:
                raise
            except BaseException as error:
                result_proxy.add_error(
                    self, traceback.format_exc(), timer(), error,
                )
                self.__context.on_error(error, self, result_proxy)