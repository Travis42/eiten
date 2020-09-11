# Basic libraries
import argparse
import math
import numpy as np
import matplotlib.pyplot as plt
import json

# Load our modules
from data_loader import DataEngine
from simulator import MontoCarloSimulator
from backtester import BackTester
from strategy_manager import StrategyManager

# Ignore warnings
import warnings
warnings.filterwarnings("ignore")

# Styling for plots
plt.style.use('seaborn-white')
plt.rc('grid', linestyle="dotted", color='#a0a0a0')
plt.rcParams['axes.edgecolor'] = "#04383F"
plt.rcParams['figure.figsize'] = (12, 6)

# Argument parsing


"""
Sample run:
python portfolio_manager.py --is_test 1 --future_bars 90 --data_granularity_minutes 3600 --history_to_use all --apply_noise_filtering 1 --market_index QQQ --only_long 1 --eigen_portfolio_number 3
"""


class ArgChecker:
    """
    Argument checker
    """

    def __init__(self, args):
        print("Checking arguments...")
        self.check_arguments(args)

    def check_arguments(self, args):
        granularity_constraints_list = [1, 5, 10, 15, 30, 60, 3600]
        granularity_constraints_list_string = ''.join(
            str(value) + "," for value in granularity_constraints_list).strip(",")

        assert not(args.data_granularity_minutes not in granularity_constraints_list), "You can only choose the following values for 'data_granularity_minutes' argument -> %s\nExiting now..." % granularity_constraints_list_string

        assert not(args.is_test == 1 and args.future_bars <
                   2), "You want to test but the future bars are less than 2. That does not give us enough data to test the model properly. Please use a value larger than 2.\nExiting now..."

        assert not(args.history_to_use != "all" and int(args.history_to_use_int) <
                   args.future_bars), "It is a good idea to use more history and less future bars. Please change these two values and try again.\nExiting now..."


class Eiten:
    def __init__(self, args):
        print("\n--* Eiten has been initialized...")
        self.args = args
        self.SAVE_PLOT = args.save_plot
        self.HISTORY_TO_USE = args.history_to_use
        self.DATA_GRANULARITY_MINUTES = args.data_granularity_minutes
        self.FUTURE_BARS_FOR_TESTING = args.future_bars
        self.APPLY_NOISE_FILTERING = args.apply_noise_filtering
        self.IS_LONG_ONLY_PORTFOLIO = args.only_long
        self.MARKET_INDEX = args.market_index
        self.IS_TEST = args.is_test
        self.EIGEN_PORTFOLIO_NUMBER = args.eigen_portfolio_number
        self.STOCKS_FILE_PATH = args.stocks_file_path

        # Create data engine
        self.dataEngine = DataEngine(self.HISTORY_TO_USE, self.DATA_GRANULARITY_MINUTES,
                                     self.FUTURE_BARS_FOR_TESTING,
                                     self.MARKET_INDEX,
                                     self.IS_TEST,
                                     self.STOCKS_FILE_PATH)

        # Monto carlo simulator
        self.simulator = MontoCarloSimulator()

        # Strategy manager
        self.strategyManager = StrategyManager()

        # Back tester
        self.backTester = BackTester()

        # Data dictionary
        self.data_dictionary = {}

        print('\n')

    def calculate_percentage_change(self, old, new):
        """
        Calculate percentage change
        """
        return ((new - old) * 100) / old

    def create_returns(self, historical_price_info):
        """
        Create log return matrix, percentage return matrix, and mean return vector
        """

        returns_matrix = []
        returns_matrix_percentages = []
        predicted_return_vectors = []
        for i in range(0, len(historical_price_info)):
            close_prices = list(historical_price_info[i]["Close"])
            log_returns = [math.log(close_prices[i] / close_prices[i - 1])
                           for i in range(1, len(close_prices))]
            percentage_returns = [self.calculate_percentage_change(
                close_prices[i - 1], close_prices[i]) for i in range(1, len(close_prices))]

            total_data = len(close_prices)
            # Expected returns in future. We can either use historical returns as future returns on try to simulate future returns and take the mean. For simulation, you can modify the functions in simulator to use here.
            future_expected_returns = np.mean([(self.calculate_percentage_change(close_prices[i - 1], close_prices[i])) / (
                total_data - i) for i in range(1, len(close_prices))])  # More focus on recent returns

            # Add to matrices
            returns_matrix.append(log_returns)
            returns_matrix_percentages.append(percentage_returns)

            # Add returns to vector
            # Assuming that future returns are similar to past returns
            predicted_return_vectors.append(future_expected_returns)

        # Convert to numpy arrays for one liner calculations
        predicted_return_vectors = np.array(predicted_return_vectors)
        returns_matrix = np.array(returns_matrix)
        returns_matrix_percentages = np.array(returns_matrix_percentages)

        return predicted_return_vectors, returns_matrix, returns_matrix_percentages

    def load_data(self):
        """
        Loads data needed for analysis
        """
        # Gather data for all stocks in a dictionary format
        # Dictionary keys will be -> historical_prices, future_prices
        self.data_dictionary = self.dataEngine.collect_data_for_all_tickers()

        # Add data to lists
        symbol_names = list(sorted(self.data_dictionary.keys()))
        historical_price_info, future_prices = [], []
        for symbol in symbol_names:
            historical_price_info.append(
                self.data_dictionary[symbol]["historical_prices"])
            future_prices.append(self.data_dictionary[symbol]["future_prices"])

        # Get return matrices and vectors
        predicted_return_vectors, returns_matrix, returns_matrix_percentages = self.create_returns(
            historical_price_info)
        return historical_price_info, future_prices, symbol_names, predicted_return_vectors, returns_matrix, returns_matrix_percentages

    def run_strategies(self):
        """
        Run strategies, back and future test them, and simulate the returns.
        """
        historical_price_info, future_prices, symbol_names, predicted_return_vectors, returns_matrix, returns_matrix_percentages = self.load_data()
        historical_price_market, future_prices_market = self.dataEngine.get_market_index_price()

        # Calculate covariance matrix
        covariance_matrix = np.cov(returns_matrix)

        # Use random matrix theory to filter out the noisy eigen values
        if self.APPLY_NOISE_FILTERING:
            print(
                "\n** Applying random matrix theory to filter out noise in the covariance matrix...\n")
            covariance_matrix = self.strategyManager.random_matrix_theory_based_cov(
                returns_matrix)

        # Get weights for the portfolio
        eigen_portfolio_weights_dictionary = self.strategyManager.calculate_eigen_portfolio(
            symbol_names, covariance_matrix, self.EIGEN_PORTFOLIO_NUMBER)
        mvp_portfolio_weights_dictionary = self.strategyManager.calculate_minimum_variance_portfolio(
            symbol_names, covariance_matrix)
        msr_portfolio_weights_dictionary = self.strategyManager.calculate_maximum_sharpe_portfolio(
            symbol_names, covariance_matrix, predicted_return_vectors)
        ga_portfolio_weights_dictionary = self.strategyManager.calculate_genetic_algo_portfolio(
            symbol_names, returns_matrix_percentages)

        # Print weights
        print("\n*% Printing portfolio weights...")
        self.print_and_plot_portfolio_weights(
            eigen_portfolio_weights_dictionary, 'Eigen Portfolio', plot_num=1)
        self.print_and_plot_portfolio_weights(
            mvp_portfolio_weights_dictionary, 'Minimum Variance Portfolio (MVP)', plot_num=2)
        self.print_and_plot_portfolio_weights(
            msr_portfolio_weights_dictionary, 'Maximum Sharpe Portfolio (MSR)', plot_num=3)
        self.print_and_plot_portfolio_weights(
            ga_portfolio_weights_dictionary, 'Genetic Algo (GA)', plot_num=4)
        self.draw_plot("output/weights.png")

        # Back test
        print("\n*& Backtesting the portfolios...")
        self.backTester.back_test(symbol_names, eigen_portfolio_weights_dictionary, self.data_dictionary,
                                  historical_price_market, self.IS_LONG_ONLY_PORTFOLIO, market_chart=True, strategy_name='Eigen Portfolio')
        self.backTester.back_test(symbol_names, mvp_portfolio_weights_dictionary, self.data_dictionary, historical_price_market,
                                  self.IS_LONG_ONLY_PORTFOLIO, market_chart=False, strategy_name='Minimum Variance Portfolio (MVP)')
        self.backTester.back_test(symbol_names, msr_portfolio_weights_dictionary, self.data_dictionary, historical_price_market,
                                  self.IS_LONG_ONLY_PORTFOLIO, market_chart=False, strategy_name='Maximum Sharpe Portfolio (MSR)')
        self.backTester.back_test(symbol_names, ga_portfolio_weights_dictionary, self.data_dictionary,
                                  historical_price_market, self.IS_LONG_ONLY_PORTFOLIO, market_chart=False, strategy_name='Genetic Algo (GA)')
        self.draw_plot("output/backtest.png")

        if self.IS_TEST:
            print("\n#^ Future testing the portfolios...")
            # Future test
            self.backTester.future_test(symbol_names, eigen_portfolio_weights_dictionary, self.data_dictionary,
                                        future_prices_market, self.IS_LONG_ONLY_PORTFOLIO, market_chart=True, strategy_name='Eigen Portfolio')
            self.backTester.future_test(symbol_names, mvp_portfolio_weights_dictionary, self.data_dictionary, future_prices_market,
                                        self.IS_LONG_ONLY_PORTFOLIO, market_chart=False, strategy_name='Minimum Variance Portfolio (MVP)')
            self.backTester.future_test(symbol_names, msr_portfolio_weights_dictionary, self.data_dictionary, future_prices_market,
                                        self.IS_LONG_ONLY_PORTFOLIO, market_chart=False, strategy_name='Maximum Sharpe Portfolio (MSR)')
            self.backTester.future_test(symbol_names, ga_portfolio_weights_dictionary, self.data_dictionary,
                                        future_prices_market, self.IS_LONG_ONLY_PORTFOLIO, market_chart=False, strategy_name='Genetic Algo (GA)')
            self.draw_plot("output/future_tests.png")

        # Simulation
        print("\n+$ Simulating future prices using monte carlo...")
        self.simulator.simulate_portfolio(symbol_names, eigen_portfolio_weights_dictionary, self.data_dictionary,
                                          future_prices_market, self.IS_TEST, market_chart=True, strategy_name='Eigen Portfolio')
        self.simulator.simulate_portfolio(symbol_names, eigen_portfolio_weights_dictionary, self.data_dictionary,
                                          future_prices_market, self.IS_TEST, market_chart=False, strategy_name='Minimum Variance Portfolio (MVP)')
        self.simulator.simulate_portfolio(symbol_names, eigen_portfolio_weights_dictionary, self.data_dictionary,
                                          future_prices_market, self.IS_TEST, market_chart=False, strategy_name='Maximum Sharpe Portfolio (MSR)')
        self.simulator.simulate_portfolio(symbol_names, ga_portfolio_weights_dictionary, self.data_dictionary,
                                          future_prices_market, self.IS_TEST, market_chart=False, strategy_name='Genetic Algo (GA)')
        self.draw_plot("output/monte_carlo.png")

    def draw_plot(self, filename="output/graph.png"):
        """
        Draw plots
        """
        plt.grid()
        plt.legend(fontsize=14)
        if self.SAVE_PLOT:
            plt.savefig(filename)
        else:
            plt.tight_layout()
            plt.show()

    def print_and_plot_portfolio_weights(self, weights_dictionary, strategy, plot_num):
        print("\n-------- Weights for %s --------" % strategy)
        symbols = list(sorted(weights_dictionary.keys()))
        symbol_weights = []
        for symbol in symbols:
            print("Symbol: %s, Weight: %.4f" %
                  (symbol, weights_dictionary[symbol]))
            symbol_weights.append(weights_dictionary[symbol])

        # Plot
        width = 0.1
        x = np.arange(len(symbol_weights))
        plt.bar(x + (width * (plot_num - 1)) + 0.05,
                symbol_weights, label=strategy, width=width)
        plt.xticks(x, symbols, fontsize=14)
        plt.yticks(fontsize=14)
        plt.xlabel("Symbols", fontsize=14)
        plt.ylabel("Weight in Portfolio", fontsize=14)
        plt.title("Portfolio Weights for Different Strategies", fontsize=14)


def main():

    argParser = argparse.ArgumentParser()
    commands = json.load(open("commands.json", "r"))
    for i in commands:
        arg_types = {"str": str, "int": int, "bool": bool}
        argParser.add_argument(i["comm"], type=arg_types[i["type"]],
                               default=i["default"], help=i["help"])

    # Get arguments
    args = argParser.parse_args()

    # Check arguments
    ArgChecker(args)

    # Run strategies
    eiten = Eiten(args)
    eiten.run_strategies()


if __name__ == '__main__':
    main()
