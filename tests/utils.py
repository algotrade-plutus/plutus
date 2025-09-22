def pytest_generate_tests(metafunc):
    """The test generator function looks up a class-level definition,
    attribute "params", which specifies which argument sets to use for each
    test function. Called once per each test function.

    "params" is a dict of test function and its arguments:
    {
        "func_name": {
            "default_params": Dict["arg_name", arg_value]
            "cases": {
                "id": str,
                "input": [Dict["arg_name", arg_value]],
                "output": [Dict["arg_name", arg_value]],
            }
        },
        ...
    }

    For each "func_name", we want to test a number of cases listed in "cases".
    For each case in "cases", there are an id, an "input" dictionary that contains
    input arguments to set up the test case and an "output" dictionary to specify
    expected outputs.
    Testers can specify default params for multiple test cases in "default_params".
    If a param is specified both in "default_params" and in a specific case, then
    the value in "default_params" will be overwritten.

    NOTE: The test generator function uses built-in metafunc to customize
    pytest.mark.parametrize decorator. For a simple demo, visit:
    https://docs.pytest.org/en/6.2.x/example/parametrize.html#paramexamples
    """
    if not (
        hasattr(metafunc.cls, "params")
        and metafunc.function.__name__ in metafunc.cls.params
    ):
        return

    kwargs = metafunc.cls.params[metafunc.function.__name__]
    testcase_ids = [case["id"] for case in kwargs["cases"]]

    default_arg_names = sorted(kwargs.get("default_params", {}))
    default_arg_values = [kwargs["default_params"][name] for name in default_arg_names]

    params = []
    for testcase in kwargs["cases"]:
        testcase_params = {}
        testcase_params.update(testcase["input"])
        testcase_params.update(testcase["output"])
        params.append(testcase_params)

    arg_names = sorted(params[0])
    arg_values = [
        ([args[name] for name in arg_names] + default_arg_values) for args in params
    ]

    arg_names += [arg_name for arg_name in default_arg_names]

    metafunc.parametrize(arg_names, arg_values, ids=testcase_ids)
